'''app.py — CLI entry and orchestration.

Wires the pipeline together: detect OS -> load config/routes -> resolve the active
profiles to units -> inspect live state -> either render the TUI (default) or run a
non-interactive command. All shell-outs honor --pretend. Path/OS overrides make
runs fully sandboxable for tests and containers.
'''

import argparse
import os
import sys

from . import osdetect
from .config import Config
from .errors import ConfigsysError
from .families import get_family
from .installState import InstallState
from .ledger import Ledger
from .paths import Paths
from .planning import expand_plan
from .routes import RouteResolver
from .runner import Runner
from .troveio import load

USER_CONFIG_TEMPLATE = '''{
    // configsys — per-machine selection. Pick which profiles (defined in the
    // repo's config.hu) apply to THIS machine. You may also locally override a
    // profile definition by redefining it here.
    configs: [ dev ]
}
'''

_STATUS_LABEL = {
    'installed': 'installed',
    'outdated': 'outdated',
    'missing': 'missing',
    'locked': 'locked',
    'unsupported': 'unsupported',
    'error': 'error',
}


class Context:
    def __init__(self, args):
        env = dict(os.environ)
        if args.home:
            env['CONFIGSYS_HOME'] = args.home
        if args.os:
            env['CONFIGSYS_OS'] = args.os
        if args.config:
            env['CONFIGSYS_CONFIG'] = args.config
        self.env = env
        self.paths = Paths(env)
        self.os_info = osdetect.detect(env)
        self.runner = Runner(pretend=args.pretend, echo=lambda m: print(m))
        self._routes_trove = None
        self._config = None

    def _cpu(self):
        '''System CPU arch for v2 selection ($ARCH assets, cpu: when-atoms).'''
        import platform
        return self.env.get('CONFIGSYS_ARCH') or platform.machine()

    @property
    def routes(self):
        # CONFIGSYS_RESOLVER=v2 selects the capability/component engine (routes2.hu);
        # default stays the live RouteResolver (routes.hu) until flipped per context.
        if self.env.get('CONFIGSYS_RESOLVER') == 'v2':
            from .v2.engine import V2Resolver
            return V2Resolver(self.paths.routes2_file, self.os_info.block,
                              self.os_info.version, self._cpu())
        if self._routes_trove is None:
            self._routes_trove = load(self.paths.routes_file)
        return RouteResolver(self._routes_trove, self.os_info.block,
                             self.os_info.version)

    @property
    def config(self):
        if self._config is None:
            self._config = Config.load(self.paths)
        return self._config

    def apply_scope_default(self, units):
        '''Stamp the machine-wide scope default onto units whose family *honors*
        scope and that don't set `scope` in their route (component field wins). Apt
        (always system) and cargo/dotfiles (per-user) are left alone.'''
        default = self.config.default_scope()
        if default:
            for rc in units.values():
                fam = get_family(rc.family, self.runner, self.paths)
                if fam is not None and fam.honors_scope:
                    rc.fields.setdefault('scope', default)
        return units

    def ensure_user_config(self):
        p = self.paths.user_config_file
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(USER_CONFIG_TEMPLATE, encoding='utf-8')
            print(f'configsys: generated {p}')

    def load_pipeline(self):
        self.ensure_user_config()
        cfg = self.config
        requested = cfg.requested()
        units = self.apply_scope_default(self.routes.resolve_names(list(requested)))
        ledger = Ledger.load(self.paths)
        states = InstallState(self.runner, ledger, self.paths).inspect(units)
        return cfg, requested, units, ledger, states


# -- commands -------------------------------------------------------------

def cmd_inspect(ctx, args):
    _cfg, requested, units, _ledger, states = ctx.load_pipeline()
    print(f'OS: {ctx.os_info.block}   profiles: {", ".join(_cfg.active_profiles)}   '
          f'units: {len(units)}\n')
    print(f'{"UNIT":30} {"STATUS":12} {"INSTALLED":20} {"LATEST"}')
    print('-' * 78)
    for key in sorted(states):
        s = states[key]
        lock = ' [locked]' if s.locked else ''
        print(f'{key:30} {_STATUS_LABEL.get(s.status, s.status):12} '
              f'{str(s.installed_version or "-"):20} {s.latest_version or "-"}{lock}')
    return 0


def _dispatch_op(ctx, names, op, *, ledger=None, version=None):
    units, roots = ctx.routes.resolve_with_roots(names)
    if not roots:
        print(f'configsys: nothing resolved for {names}')
        return 1
    ctx.apply_scope_default(units)
    # Apply the requested op to the *named* units; expand_plan folds in dependency
    # installs (e.g. apt\flatpak before flatpak\firefox) and orders the whole thing.
    base_plan = [(op, key, units[key]) for key in sorted(roots)]
    plan = expand_plan(base_plan, units)

    rc_code = 0
    for cur_op, key, rc in plan:
        fam = get_family(rc.family, ctx.runner, ctx.paths)
        if fam is None:
            print(f'skip {key}: family "{rc.family}" not yet supported')
            continue
        print(f'{cur_op} {key} (pkg: {rc.name}) ...')
        if cur_op == 'install':
            res = fam.install(rc)
        elif cur_op == 'remove':
            res = fam.uninstall(rc)
        elif cur_op == 'upgrade':
            res = fam.upgrade(rc)
        elif cur_op == 'set-version':
            res = fam.set_version(rc, version)
        elif cur_op == 'lock':
            res = fam.lock(rc)
            if res.ok and ledger is not None:
                ledger.set_lock(key, True)
        elif cur_op == 'unlock':
            res = fam.unlock(rc)
            if res.ok and ledger is not None:
                ledger.set_lock(key, False)
        else:
            print(f'unknown op {cur_op}')
            return 2
        if not res.ok:
            rc_code = res.returncode or 1
            print(f'  -> FAILED (exit {res.returncode})')
        else:
            print('  -> ok')
    if ledger is not None:
        ledger.save(ctx.paths)
    return rc_code


def cmd_install(ctx, args):
    return _dispatch_op(ctx, args.names, 'install')


def cmd_remove(ctx, args):
    return _dispatch_op(ctx, args.names, 'remove')


def cmd_upgrade(ctx, args):
    return _dispatch_op(ctx, args.names, 'upgrade')


def cmd_lock(ctx, args):
    return _dispatch_op(ctx, args.names, 'lock', ledger=Ledger.load(ctx.paths))


def cmd_unlock(ctx, args):
    return _dispatch_op(ctx, args.names, 'unlock', ledger=Ledger.load(ctx.paths))


def cmd_set_version(ctx, args):
    return _dispatch_op(ctx, [args.name], 'set-version', version=args.version)


def cmd_refresh(ctx, args):
    from .versions import discover, source_key
    _cfg, _req, units, _ledger, _states = ctx.load_pipeline()
    print('Refreshing discovered versions...')
    seen = {}
    for key in sorted(units):
        rc = units[key]
        fam = get_family(rc.family, ctx.runner, ctx.paths)
        if fam is None:
            continue
        # use the family's arch-substituted spec so the cache key matches what the
        # family looks up at install time (and warms both version + asset url)
        spec = fam._disco_spec(rc)
        if not isinstance(spec, dict) or 'static' in spec:
            continue
        sk = source_key(spec)
        if sk in seen:
            continue
        seen[sk] = discover(spec, ctx.paths, refresh=True)
        print(f'  {sk:44} -> {seen[sk] or "(unknown)"}')
    if not seen:
        print('  (no discoverable versions in the active profiles)')
    elif any(v is None for v in seen.values()) and 'CONFIGSYS_GITHUB_TOKEN' not in ctx.env \
            and 'GITHUB_TOKEN' not in ctx.env:
        print('\nSome lookups failed (network or GitHub rate limit). Set '
              'CONFIGSYS_GITHUB_TOKEN or GITHUB_TOKEN to lift the API limit.')
    return 0


def cmd_tui(ctx, args):
    if not sys.stdout.isatty() or not sys.stdin.isatty():
        print('configsys: not an interactive terminal; showing inspection instead.\n')
        return cmd_inspect(ctx, args)
    try:
        from .tui import run as run_tui
    except ImportError:
        print('configsys: TUI not available; showing inspection instead.\n')
        return cmd_inspect(ctx, args)
    return run_tui(ctx)


# -- argument parsing -----------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(prog='configsys',
                                description='Sync OS-native software from a profile.')
    p.add_argument('--pretend', action='store_true',
                   help='print commands instead of executing them (dry run)')
    p.add_argument('--os', help='override detected OS routes block (e.g. pop_os!)')
    p.add_argument('--home', help='override HOME base for all paths (sandboxing)')
    p.add_argument('--config', help='override the per-machine selector file path')

    sub = p.add_subparsers(dest='command')
    sub.add_parser('inspect', help='show install state of the active profiles')

    for name, help_ in (('install', 'install components'),
                        ('remove', 'uninstall components'),
                        ('upgrade', 'upgrade components to latest'),
                        ('lock', 'version-lock components'),
                        ('unlock', 'remove version lock')):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument('names', nargs='+', help='component names (from a profile/routes)')

    sv = sub.add_parser('set-version', help='pin a component to a specific version')
    sv.add_argument('name')
    sv.add_argument('version')

    sub.add_parser('refresh', help='re-query latest versions from their sources')
    sub.add_parser('tui', help='interactive TUI (default)')
    return p


_COMMANDS = {
    'inspect': cmd_inspect,
    'install': cmd_install,
    'remove': cmd_remove,
    'upgrade': cmd_upgrade,
    'lock': cmd_lock,
    'unlock': cmd_unlock,
    'set-version': cmd_set_version,
    'refresh': cmd_refresh,
    'tui': cmd_tui,
}


def main(argv=None):
    args = build_parser().parse_args(argv)
    command = args.command or 'tui'
    ctx = Context(args)
    try:
        return _COMMANDS[command](ctx, args)
    except ConfigsysError as e:
        print(f'configsys: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
