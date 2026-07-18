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
from .drivers import get_driver
from .installState import InstallState
from .ledger import Ledger
from .paths import Paths
from .planning import expand_plan
from .routes import Resolver
from .runner import Runner

USER_CONFIG_TEMPLATE = '''{
    // configsys — this machine's settings and overrides. Overlays the repo's
    // config.hu + routes.hu section by section (your definitions win).

    // Pull in other files (profiles + components; definitions-only). Relative paths
    // resolve against THIS file's directory. Handy for per-project dependency sets.
    // include: [ ~/src/myproject/configsys.hu ]

    // Data plugins from git repos, pinned to a ref, then `configsys plugin sync`. A
    // github:/gitlab: source has a colon so it must be quoted.
    // plugins: [ { source: "github:someone/configsys-opensuse"  ref: v1.2.0 } ]

    // Which profiles (from the repo's config.hu, your `profiles:`, or an include) apply here.
    configs: [ dev ]

    // Machine-wide default install scope for scope-honoring drivers (user | system).
    // scope: system

    // Project discovery walks up from the CWD for .configsys.hu / .configsys-*.hu and
    // auto-activates their profiles. Turn it off, or suppress specific profiles:
    // discover: false
    // ignore-profiles: [ some-profile ]

    // Pins — the light way to reroute without redefining a component:
    //   component -> driver  (binding-pin: force a method)
    //   capability -> component  (provider-pin: force who satisfies a requirement)
    // pins: {
    //     steam: flatpak
    // }

    // Define or shadow profiles (a profile is a flat list of component names).
    // profiles: {
    //     dev: [ btop, neovim, gcc-15, gdb ]
    // }

    // Override component routes: redefine one (all-or-nothing), add your own, or
    // remove one with {}. See routes.hu for the component shape.
    // components: {
    //     steam: { install: [ { via: flatpak  hub: flathub  app: com.valvesoftware.Steam } ] }
    //     apod:  {}
    // }
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
        self._config = None
        self._discovered = None
        self._plugin_files = None
        self._plugin_code_loaded = False
        self.plugin_code_warnings = []   # code plugins that ship code but were gated out
        self.plugin_pending_vias = set()  # via names those gated-out plugins would provide
        self.resolve_errors = {}      # {requested_name: message} from the last resilient resolve
        self._migrate_user_config()

    @property
    def plugin_files(self):
        '''Data-file layers contributed by declared+synced+compatible plugins (in declaration
        order). Uses what's on disk; `configsys plugin sync` puts it there.'''
        if self._plugin_files is None:
            from . import plugins
            decls = plugins.declared(self.paths.user_config_file)
            self._plugin_files = plugins.layer_files(self.paths.plugins_dir, decls)
        return self._plugin_files

    def _migrate_user_config(self):
        '''One-time move of a legacy ~/configsys.hu into ~/.config/configsys/configsys.hu.'''
        if self.env.get('CONFIGSYS_CONFIG'):
            return                                       # explicit path -> nothing to migrate
        new, legacy = self.paths.user_config_file, self.paths.legacy_user_config_file
        if not new.exists() and legacy.exists() and legacy != new:
            new.parent.mkdir(parents=True, exist_ok=True)
            legacy.rename(new)
            print(f'configsys: moved {legacy} -> {new}')

    def _cpu(self):
        '''System CPU arch for routing ($ARCH assets, cpu: when-atoms).'''
        import platform
        return self.env.get('CONFIGSYS_ARCH') or platform.machine()

    @property
    def discovered(self):
        '''Project configsys files (.configsys.hu + .configsys-*.hu) found by walking up from
        the CWD to the nearest project root. Disabled by CONFIGSYS_NO_DISCOVER.'''
        if self._discovered is None:
            from . import layers
            if self.env.get('CONFIGSYS_NO_DISCOVER') or self._discovery_disabled():
                self._discovered = []
            else:
                start = self.env.get('CONFIGSYS_CWD') or os.getcwd()
                self._discovered = layers.discover(start, str(self.paths.home))
        return self._discovered

    def _discovery_disabled(self):
        '''`discover: false` in the user config (read directly, before the layer stack).'''
        from . import layers
        val = layers.read_setting(self.paths.user_config_file, 'discover')
        return val is not None and str(val).lower() in ('false', 'no', '0', 'off')

    def discovery_warnings(self):
        '''Warnings for discovered files that were skipped (malformed/cyclic).'''
        from . import layers
        if not self.discovered:
            return []
        return layers.expand_tolerant([(d, 'discover') for d in self.discovered],
                                      {'discover'})[1]

    def ensure_plugin_code(self):
        '''Import + register the drivers of trusted code plugins, once, before any resolution
        (so `via: <plugin-driver>` resolves). Untrusted/incompatible/broken code plugins are
        collected into plugin_code_warnings and simply left unregistered (their `via:` stays
        unknown -> the component degrades to a resilient error row). Idempotent.'''
        if self._plugin_code_loaded:
            return
        self._plugin_code_loaded = True
        from . import plugins
        from .drivers import register_driver
        decls = plugins.declared(self.paths.user_config_file)
        _loaded, skipped = plugins.load_code(self.runner, self.paths.plugins_dir,
                                             self.paths.plugin_trust_file, decls, register_driver)
        self.plugin_code_warnings = [f'plugin {key}: {reason}' for key, reason in skipped]
        # a gated-out code plugin's drivers are "known but unavailable": collect the via names
        # it declares (manifest provides.drivers) so `check` treats them as pending-trust, not
        # unknown typos — the trust nudge above is the single actionable message.
        pending = set()
        for key, _reason in skipped:
            provides = plugins.read_manifest(self.paths.plugins_dir / key).get('provides') or {}
            pending.update(provides.get('drivers') or [])
        self.plugin_pending_vias = pending

    @property
    def routes(self):
        # layer stack: routes.hu < discovered project files < ~/configsys.hu (components
        # overlay + pins). A malformed discovered file is skipped, not fatal.
        self.ensure_plugin_code()     # register trusted plugin drivers before `via:` resolves
        return Resolver(self.paths.routes_file, self.os_info.block,
                        self.os_info.version, self._cpu(),
                        pins=self.config.pins(),
                        overrides_path=self.paths.user_config_file,
                        discovered=self.discovered, plugin_files=self.plugin_files)

    @property
    def config(self):
        if self._config is None:
            self._config = Config.load(self.paths, self.discovered, self.plugin_files)
        return self._config

    def apply_scope_default(self, units):
        '''Stamp the machine-wide scope default onto units whose driver *honors*
        scope and that don't set `scope` in their route (component field wins). Apt
        (always system) and cargo/dotfiles (per-user) are left alone.'''
        default = self.config.default_scope()
        if default:
            for rc in units.values():
                fam = get_driver(rc.driver, self.runner, self.paths)
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
        # resilient: a requested component that can't route here becomes a reported error
        # (self.resolve_errors), not a hard stop — so one bad entry in the active set (e.g.
        # from an auto-activated project profile) can't brick inspect/the TUI.
        units, self.resolve_errors = self.routes.resolve_resilient(list(requested))
        self.apply_scope_default(units)
        ledger = Ledger.load(self.paths)
        states = InstallState(self.runner, ledger, self.paths).inspect(units)
        return cfg, requested, units, ledger, states


# -- commands -------------------------------------------------------------

def cmd_inspect(ctx, args):
    _cfg, requested, units, _ledger, states = ctx.load_pipeline()
    print(f'OS: {ctx.os_info.block}   profiles: {", ".join(_cfg.active_profiles)}   '
          f'units: {len(units)}')
    if ctx.discovered:
        files = ', '.join(os.path.basename(d) for d in ctx.discovered)
        print(f'project: {os.path.dirname(ctx.discovered[0])}  ({files})')
    for w in ctx.discovery_warnings():
        print(f'  warn: {w}')
    print()
    print(f'{"UNIT":30} {"STATUS":12} {"INSTALLED":20} {"LATEST"}')
    print('-' * 78)
    for key in sorted(states):
        s = states[key]
        lock = ' [locked]' if s.locked else ''
        print(f'{key:30} {_STATUS_LABEL.get(s.status, s.status):12} '
              f'{str(s.installed_version or "-"):20} {s.latest_version or "-"}{lock}')
    # resilient: requested components that couldn't route here — shown, not fatal
    if ctx.resolve_errors:
        print('\nunresolved (requested but not routable here):')
        for name in sorted(ctx.resolve_errors):
            print(f'  {name:28} error        {ctx.resolve_errors[name]}')
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
        fam = get_driver(rc.driver, ctx.runner, ctx.paths)
        if fam is None:
            print(f'skip {key}: driver "{rc.driver}" not yet supported')
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
        fam = get_driver(rc.driver, ctx.runner, ctx.paths)
        if fam is None:
            continue
        # use the driver's arch-substituted spec so the cache key matches what the
        # driver looks up at install time (and warms both version + asset url)
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


# -- where: explain a component's routing ---------------------------------

def _fmt_val(v):
    '''Compact one-line rendering of a binding detail value.'''
    if isinstance(v, dict):
        return '{' + ' '.join(f'{k}={_fmt_val(x)}' for k, x in v.items()) + '}'
    if isinstance(v, list):
        return '[' + ', '.join(_fmt_val(x) for x in v) + ']'
    s = str(v)
    return s if len(s) <= 60 else s[:57] + '...'


def _fmt_binding(b, selected):
    when = b.when if b.when else 'always'
    details = '  '.join(f'{k}={_fmt_val(v)}' for k, v in b.details.items())
    mark = '  <- selected here' if selected else ''
    return f'    - via {b.via}   when: {when}' + (f'   {details}' if details else '') + mark


def _layer_label(source, paths):
    '''A friendly label for a source file: 'routes.hu' for the repo routing base, else the
    path with $HOME collapsed to ~ (so user/discovered/included files show where they live).'''
    if source in (str(paths.routes_file), paths.routes_file):
        return 'routes.hu'
    s, home = str(source), str(paths.home)
    return '~' + s[len(home):] if home and s.startswith(home) else s


def _source_label(comp, paths):
    '''Human provenance line for a component's definition.'''
    where = _layer_label(comp.source, paths)
    if where == 'routes.hu':
        return 'routes.hu'
    if not comp.bindings:
        return f'{where}   (removes routes.hu\'s definition)' if comp.shadows else \
               f'{where}   (defined empty / removed)'
    return f'{where}   (overrides routes.hu)' if comp.shadows else f'{where}   (new; not in routes.hu)'


def cmd_where(ctx, args):
    from .resolve import select_binding, ResolveError
    name = args.name
    r = ctx.routes
    comp = r.components.get(name)
    if comp is None:
        print(f'configsys: unknown component "{name}" '
              f'(not in routes.hu or your ~/configsys.hu)')
        return 1

    print(f'\n{name}')
    print(f'  defined in  {_source_label(comp, ctx.paths)}')
    if comp.provides:
        print(f'  provides    {", ".join(comp.provides)}')
    if comp.requires:
        print(f'  requires    {", ".join(comp.requires)}')
    pinned = r.pins.get(name)
    if pinned is not None:
        print(f'  pinned      via:{pinned}   (from ~/configsys.hu)')

    # which binding wins in this machine's context (if any)
    cx = r.cascade.context(r.block, r.version, r.cpu)
    selected = None
    if comp.bindings:
        try:
            selected = select_binding(comp, r.cascade, cx, r.pins)
        except ResolveError:
            selected = None  # bindings exist but none match here
        print('  bindings')
        for b in comp.bindings:
            print(_fmt_binding(b, b is selected))

    # how it actually resolves on this machine
    ver = f' {r.version}' if r.version else ''
    print(f'\n  on {r.block}{ver} ({r.cpu}):')
    if not comp.bindings:
        print('    nothing (removed)')
        return 0
    try:
        units = r.resolve_names([name])
    except ResolveError as e:
        print(f'    ERROR: {e}')
        return 0
    if not units:
        print('    nothing')
        return 0
    own = {k for k in units if k.split('\\', 1)[-1] == name}
    for key in sorted(units):
        rc = units[key]
        tag = '' if key in own else '   (dep)'
        pkg = f'  pkg {rc.name}' if rc.name else ''
        print(f'    {key}{pkg}{tag}')
    return 0


# -- check: lint the merged config ----------------------------------------

def _issue_loc(issue, paths):
    if issue.component is None:
        return ''
    src = f' [{_layer_label(issue.source, paths)}]' if issue.source else ''
    return f"component '{issue.component}'{src}: "


def cmd_check(ctx, args):
    '''Lint the whole merged config (repo + your ~/configsys.hu + includes) without installing.'''
    from . import layers, routes, routecheck
    ctx.ensure_plugin_code()          # register trusted plugin drivers so `via:` validates
    try:
        cascade, components, drivers = routes.load(
            ctx.paths.routes_file, ctx.paths.user_config_file, ctx.discovered,
            ctx.plugin_files, validate=False)
        roots = ([(ctx.paths.routes_file, 'repo'), (ctx.paths.config_file, 'repo')]
                 + [(p, 'plugin') for p in ctx.plugin_files]
                 + [(d, 'discover') for d in ctx.discovered]
                 + [(ctx.paths.user_config_file, 'user')])
        layer_list, _w = layers.expand_tolerant(roots, {'discover', 'plugin'})
    except ConfigsysError as e:
        print(f'configsys: {e}')          # a parse/structural error before we can lint
        return 1

    issues = routecheck.validate(components, cascade, drivers,
                                 pending_vias=ctx.plugin_pending_vias)
    include_warnings = layers.ignored_section_warnings(layer_list)

    # profile references: a selected profile naming a component that doesn't exist
    prof_issues = []
    try:
        for prof in ctx.config.active_profiles:
            for cname in ctx.config.profile_components(prof):
                if cname not in components:
                    prof_issues.append((prof, cname))
    except ConfigsysError:
        pass  # malformed profiles surface on their own path

    # pins: value must be a known driver (binding-pin) or a known component (provider-pin)
    from .drivers import supported_names
    valid_via = {'native', 'parts'} | supported_names()
    pin_issues = []
    for key, val in ctx.config.pins().items():
        if val in valid_via:
            if key not in components:
                pin_issues.append(f"pin '{key}: {val}': component '{key}' does not exist")
        elif val not in components:
            pin_issues.append(f"pin '{key}: {val}': '{val}' is neither a known driver "
                              f'(binding-pin) nor a component (provider-pin)')

    errors = [i for i in issues if i.is_error]
    warnings = [i for i in issues if not i.is_error]
    code_warnings = ctx.plugin_code_warnings
    if (not errors and not warnings and not prof_issues and not pin_issues
            and not include_warnings and not code_warnings):
        print(f'configsys: OK — {len(components)} components, no issues')
        return 0

    for i in errors:
        print(f'  ERROR   {_issue_loc(i, ctx.paths)}{i.message}')
    for prof, cname in prof_issues:
        print(f"  ERROR   profile '{prof}': unknown component '{cname}'")
    for msg in pin_issues:
        print(f'  ERROR   {msg}')
    for i in warnings:
        print(f'  warn    {_issue_loc(i, ctx.paths)}{i.message}')
    for msg in include_warnings:
        print(f'  warn    {msg}')
    for msg in code_warnings:
        print(f'  warn    {msg}')
    n_err = len(errors) + len(prof_issues) + len(pin_issues)
    n_warn = len(warnings) + len(include_warnings) + len(code_warnings)
    print(f'\nconfigsys: {n_err} error(s), {n_warn} warning(s) '
          f'across {len(components)} components')
    return 1 if n_err else 0


# -- plugin: declare in `plugins:`, sync from git -------------------------

def _find_decl(decls, plugins_dir, ident):
    '''A declared plugin matching `ident` — its source, dir basename, or manifest name.'''
    from . import plugins
    for d in decls:
        dn = plugins.dir_name(d['source'])
        if ident in (d['source'], dn) or plugins.read_manifest(plugins_dir / dn).get('name') == ident:
            return d
    return None


def _sync_and_report(ctx, decls):
    from . import plugins
    ctx.ensure_plugin_code()     # register transports from already-trusted plugins before sync
    for name, action in plugins.sync(ctx.runner, ctx.paths.plugins_dir, decls):
        print(f'  {action:8} {name}')


def cmd_plugin(ctx, args):
    from . import plugins
    decls = plugins.declared(ctx.paths.user_config_file)
    sub = getattr(args, 'plugin_command', None) or 'list'

    if sub == 'sync':
        if not decls:
            print('configsys: no plugins declared (add one: `configsys plugin add <source>`)')
            return 0
        _sync_and_report(ctx, decls)
        return 0

    if sub == 'add':
        ctx.ensure_user_config()                    # the file must exist to edit it
        existing = next((d for d in decls if d['source'] == args.source), None)
        if existing:
            existing['ref'] = args.ref
        else:
            decls.append({'source': args.source, 'ref': args.ref})
        plugins.set_declared(ctx.paths.user_config_file, decls)
        print(f'configsys: {"re-pinned" if existing else "added"} {args.source}'
              + (f' @{args.ref}' if args.ref else ''))
        _sync_and_report(ctx, [d for d in decls if d['source'] == args.source])
        return 0

    if sub == 'remove':
        target = _find_decl(decls, ctx.paths.plugins_dir, args.name)
        if target is None:
            print(f'configsys: no declared plugin matches {args.name!r}')
            return 1
        plugins.set_declared(ctx.paths.user_config_file, [d for d in decls if d is not target])
        pdir = ctx.paths.plugins_dir / plugins.dir_name(target['source'])
        if pdir.exists() and not ctx.runner.pretend:
            import shutil
            shutil.rmtree(pdir)
        print(f'configsys: removed {target["source"]}')
        return 0

    if sub == 'update':
        target = _find_decl(decls, ctx.paths.plugins_dir, args.name)
        if target is None:
            print(f'configsys: no declared plugin matches {args.name!r}')
            return 1
        if args.ref:
            target['ref'] = args.ref
            plugins.set_declared(ctx.paths.user_config_file, decls)
            print(f'configsys: re-pinned {target["source"]} @{args.ref}')
        _sync_and_report(ctx, [target])
        return 0

    if sub == 'trust':
        target = _find_decl(decls, ctx.paths.plugins_dir, args.name)
        if target is None:
            print(f'configsys: no declared plugin matches {args.name!r}')
            return 1
        key = plugins.dir_name(target['source'])         # store key: stable across commits
        pdir = ctx.paths.plugins_dir / key
        if not pdir.exists():
            print(f'configsys: {key} is not synced — run: configsys plugin sync')
            return 1
        manifest = plugins.read_manifest(pdir)
        disp = manifest.get('name', key)                  # friendly name for display
        if not manifest.get('code'):
            print(f'configsys: {disp} ships no code — nothing to trust')
            return 0
        commit = plugins.plugin_commit(ctx.runner, pdir)
        if commit is None:
            print(f'configsys: could not read {disp}’s commit (not a git checkout?)')
            return 1
        plugins.set_trust(ctx.paths.plugin_trust_file, key, commit)
        print(f'configsys: trusted {disp} @ {commit[:12]} — its code will run during installs')
        return 0

    if sub == 'untrust':
        target = _find_decl(decls, ctx.paths.plugins_dir, args.name)
        key = plugins.dir_name(target['source']) if target else args.name
        pdir = ctx.paths.plugins_dir / key
        disp = plugins.read_manifest(pdir).get('name', key) if pdir.exists() else key
        if plugins.remove_trust(ctx.paths.plugin_trust_file, key):
            print(f'configsys: untrusted {disp}')
            return 0
        print(f'configsys: {disp} was not trusted')
        return 0

    if sub == 'list':
        rows = plugins.status(ctx.paths.plugins_dir, decls,
                              runner=ctx.runner, trust_file=ctx.paths.plugin_trust_file)
        if not rows:
            print('configsys: no plugins declared')
            return 0
        for r in rows:
            if not r['synced']:
                state = 'not synced (run: configsys plugin sync)'
            elif not r['abi_ok']:
                state = f'incompatible (needs plugin ABI {r["requires_abi"]})'
            else:
                state = 'ok'
                cs = r['code_state']
                if cs == 'trusted':
                    state += '  [code trusted]'
                elif cs == 'untrusted':
                    state += f'  [ships code — untrusted; run: configsys plugin trust {r["name"]}]'
                elif cs == 'changed':
                    state += (f'  [code changed since trust — re-approve: '
                              f'configsys plugin trust {r["name"]}]')
            ref = f' @{r["ref"]}' if r['ref'] else ''
            print(f'  {r["name"]:22} {r["source"]}{ref}')
            print(f'  {"":22} {state}')
        return 0

    print(f'configsys: unknown plugin subcommand {sub!r}')
    return 2


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

    wh = sub.add_parser('where', help='explain a component: source layer, bindings, and how '
                                      'it resolves on this machine')
    wh.add_argument('name', help='component name')

    sub.add_parser('check', help='lint the merged config (repo + ~/configsys.hu) without '
                                 'installing')

    pl = sub.add_parser('plugin', help='data plugins: declare in `plugins:`, then sync from git')
    plsub = pl.add_subparsers(dest='plugin_command')
    plsub.add_parser('list', help='declared plugins + their sync/ABI status')
    plsub.add_parser('sync', help='clone/fetch declared plugins to their pinned refs')
    pa = plsub.add_parser('add', help='declare a plugin and sync it')
    pa.add_argument('source', help='github:owner/repo | gitlab:owner/repo | git URL | local path')
    pa.add_argument('--ref', help='pin to a tag / commit / branch')
    pr = plsub.add_parser('remove', help='undeclare a plugin and delete its synced copy')
    pr.add_argument('name', help='plugin name, source, or dir')
    pu = plsub.add_parser('update', help="re-sync a plugin (move its pin with --ref)")
    pu.add_argument('name', help='plugin name, source, or dir')
    pu.add_argument('--ref', help='new tag / commit / branch to pin to')
    pt = plsub.add_parser('trust', help="approve a code plugin's current commit to run during installs")
    pt.add_argument('name', help='plugin name, source, or dir')
    pun = plsub.add_parser('untrust', help="revoke a code plugin's trust")
    pun.add_argument('name', help='plugin name, source, or dir')

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
    'where': cmd_where,
    'check': cmd_check,
    'plugin': cmd_plugin,
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
