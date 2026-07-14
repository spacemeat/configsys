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

    @property
    def routes(self):
        if self._routes_trove is None:
            self._routes_trove = load(self.paths.routes_file)
        return RouteResolver(self._routes_trove, self.os_info.block)

    def ensure_user_config(self):
        p = self.paths.user_config_file
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(USER_CONFIG_TEMPLATE)
            print(f'configsys: generated {p}')

    def load_pipeline(self):
        self.ensure_user_config()
        cfg = Config.load(self.paths)
        requested = cfg.requested()
        units = self.routes.resolve_names(list(requested))
        ledger = Ledger.load(self.paths)
        states = InstallState(self.runner, ledger).inspect(units)
        return cfg, requested, units, ledger, states

    def resolve(self, names):
        return self.routes.resolve_names(names)


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
    units = ctx.resolve(names)
    if not units:
        print(f'configsys: nothing resolved for {names}')
        return 1
    rc_code = 0
    for key in sorted(units):
        rc = units[key]
        fam = get_family(rc.family, ctx.runner)
        if fam is None:
            print(f'skip {key}: family "{rc.family}" not yet supported')
            continue
        print(f'{op} {key} (pkg: {rc.name}) ...')
        if op == 'install':
            res = fam.install(rc)
        elif op == 'remove':
            res = fam.uninstall(rc)
        elif op == 'upgrade':
            res = fam.upgrade(rc)
        elif op == 'set-version':
            res = fam.set_version(rc, version)
        elif op == 'lock':
            res = fam.lock(rc)
            if res.ok and ledger is not None:
                ledger.set_lock(key, True)
        elif op == 'unlock':
            res = fam.unlock(rc)
            if res.ok and ledger is not None:
                ledger.set_lock(key, False)
        else:
            print(f'unknown op {op}')
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


def cmd_tui(ctx, args):
    try:
        from .tui import run as run_tui
    except ImportError:
        print('configsys: TUI not available yet; showing inspection instead.\n')
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
