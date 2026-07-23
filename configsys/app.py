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
from . import report
from . import reportgen


def _unskip(w):
    '''Drop a leading "skipped " tag from a load-warning for clean display.'''
    return w[len('skipped '):] if w.startswith('skipped ') else w
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

    // Which profiles (from the repo's config.hu, your `profiles:`, a `primary` plugin, or an
    // include) apply here. Left commented so a `primary` plugin's `configs:` provides the
    // default; uncomment to set or override it on THIS machine.
    // configs: [ dev ]

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

    // Define, amend, or shadow profiles. A profile is an ordered list of terms: a bare `name`
    // adds a component, `+name` includes another profile's members, `~name` removes one (order
    // matters). `+<this profile's own name>` amends the same profile from the layer below
    // (super), instead of replacing it; a bare redefine (no `+self`) still replaces wholesale.
    // profiles: {
    //     dev:     [ btop, neovim, gcc-15, gdb ]
    //     desktop: [ +dev, steam, ~gdb ]          // everything in dev, plus steam, minus gdb
    //     user:    [ +user, apod ]                // the base `user` profile PLUS apod
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
        level = report.SILENT if getattr(args, 'silent', False) \
            else min(getattr(args, 'verbose', 0), report.DEBUG)
        self.reporter = report.Reporter(level)
        self.runner = Runner(pretend=args.pretend, echo=lambda m: print(m))
        self._config = None
        self._discovered = None
        self._plugin_files = None
        self._plugin_code_loaded = False
        self.plugin_code_warnings = []   # code plugins that ship code but were gated out
        self.plugin_code_conflicts = []  # code-level registration collisions (version-source/transport)
        self.plugin_pending_vias = set()  # via names those gated-out plugins would provide
        self.resolve_errors = {}      # {requested_name: message} from the last resilient resolve
        self._migrate_user_config()

    @property
    def plugin_files(self):
        '''Data-file layers contributed by declared+synced+compatible plugins (in declaration
        order). Uses what's on disk; `configsys plugin sync` puts it there.'''
        if self._plugin_files is None:
            from . import plugins
            decls = plugins.effective_declared(self.paths.user_config_file, self.paths.plugins_dir)
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

    def diagnostics(self, states=None):
        '''Every non-fatal skip/warning from loading + resolution, as {level, tag, text} (deduped
        by text). This is the "silent stuff" — a malformed layer that got dropped (the exact class
        that can make a whole primary plugin vanish), a plugin quarantined / untrusted / ABI-
        incompatible, a machine-setting section ignored from a non-primary plugin, a requested
        component that can't route here. With `states`, also flags scope mismatches (installed at
        a different scope than the config declares — `fix-scope` reconciles them). Surfaced by the
        TUI (! page) and inspect. Call after a load so config/routes/resolve_errors are populated.'''
        from . import plugins
        out, seen = [], set()

        def add(level, tag, text):
            if text and text not in seen:
                seen.add(text)
                out.append({'level': level, 'tag': tag, 'text': text})

        def unskip(w):                                   # tag already says "skipped"
            return w[len('skipped '):] if w.startswith('skipped ') else w

        if osdetect.is_atomic(self.os_info.block):
            add('warn', 'atomic',
                'atomic/immutable OS detected — configsys atomic routing is NEW and not yet '
                'validated on real hardware. Here CLI tools install via Homebrew, apps via '
                'Flatpak, and `via: rpm-ostree` layering is reboot-gated. Dev toolchains, the '
                'GPU/Vulkan stack, docker and AppImages are NOT managed here — use distrobox, '
                'podman, or rpm-ostree for those. Review the plan before you run any op, and '
                'please report anything that misroutes.')

        self.ensure_plugin_code()                        # populates plugin_code_warnings
        for w in getattr(self.config, 'load_warnings', []):
            add('error', 'skipped', unskip(w))           # a dropped config layer (primary/plugin/project)
        for w in getattr(self.routes, 'load_warnings', []):
            add('error', 'skipped', unskip(w))           # a dropped routes layer or component
        for w in self.discovery_warnings():
            add('error', 'skipped', unskip(w))
        for w in self.config.ignored_section_warnings():
            add('warn', 'ignored', w)
        for w in self.plugin_code_warnings:
            add('warn', 'code', w)
        decls = plugins.effective_declared(self.paths.user_config_file, self.paths.plugins_dir)
        for r in plugins.status(self.paths.plugins_dir, decls,
                                trust_file=self.paths.plugin_trust_file):
            if not r['synced']:
                add('warn', 'unsynced', f"{r['name']}: not synced (run: configsys plugin sync)")
            elif r['checksum'] == 'mismatch':
                add('error', 'quarantined',
                    f"{r['name']}: content ≠ declared sha256 — quarantined")
            elif not r['abi_ok']:
                add('warn', 'incompatible', f"{r['name']}: needs plugin ABI {r['requires_abi']}")
        for name in sorted(self.resolve_errors or {}):
            add('error', 'unroutable', f"{name}: {self.resolve_errors[name]}")
        for key, st in sorted((states or {}).items()):
            if not (st.present and st.scope):
                continue
            fam = get_driver(st.component.driver, self.runner, self.paths)
            if fam is not None and fam.honors_scope:
                target = fam.scope(st.component)
                if st.scope != target:
                    add('warn', 'scope', f"{key}: installed {st.scope}, config declares "
                                         f"{target} — run: configsys fix-scope")
        return out

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
        decls = plugins.effective_declared(self.paths.user_config_file, self.paths.plugins_dir)
        code_conflicts = []
        _loaded, skipped = plugins.load_code(self.paths.plugins_dir, self.paths.plugin_trust_file,
                                             decls, register_driver, conflicts=code_conflicts)
        self.plugin_code_warnings = [f'plugin {key}: {reason}' for key, reason in skipped]
        self.plugin_code_conflicts = code_conflicts
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

    def ensure_user_config(self, *, offer_primary=False):
        p = self.paths.user_config_file
        if p.exists():
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(USER_CONFIG_TEMPLATE, encoding='utf-8')
        print(f'configsys: generated {p}')
        if offer_primary:
            self._offer_primary()          # first-run only: point configsys at a personal plugin

    def _offer_primary(self):
        '''First-run offer to designate a `primary` personal-config plugin. Interactive only
        (a non-TTY / scripted run just skips it — no nag). On a value, bless it (register +
        sync); Enter or "none" skips.'''
        import sys
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return
        print('\nYour personal config (profiles, scope, pins) can live in a "primary" plugin so')
        print("it travels with you. Point configsys at yours now, or press Enter to skip.")
        try:
            ans = input('  primary plugin  <provider>:<user>/<name>  [none]: ').strip()
        except EOFError:
            return
        if not ans or ans.lower() == 'none':
            return
        ok, msg = _bless_primary(self, ans)
        print(f'configsys: {msg}')

    def load_pipeline(self):
        r = self.reporter
        self.ensure_user_config(offer_primary=True)
        cfg = self.config
        r.event(report.VERBOSE, f'  config: {len(cfg.active_profiles)} profile(s) active '
                                f'({", ".join(cfg.active_profiles)})')
        for w in getattr(cfg, 'load_warnings', []):     # dropped config layers, streamed as found
            r.error(_unskip(w))
        routes = self.routes                            # one Resolver — reused for reporting below
        self._report_layers(routes)                     # -v: the component layer stack, low→high
        for w in getattr(routes, 'load_warnings', []):
            r.error(_unskip(w))
        requested = cfg.requested()
        # resilient: a requested component that can't route here becomes a reported error
        # (self.resolve_errors), not a hard stop — so one bad entry in the active set (e.g.
        # from an auto-activated project profile) can't brick inspect/the TUI.
        units, self.resolve_errors = routes.resolve_resilient(list(requested))
        for name in sorted(self.resolve_errors or {}):
            r.error(f'{name}: {self.resolve_errors[name]}')
        r.event(report.VERBOSE, f'  resolved {len(requested)} requested -> {len(units)} unit(s)')
        self._report_routing(routes, requested)         # -v overrides, -vv winning binding + why
        self.apply_scope_default(units)
        ledger = Ledger.load(self.paths)
        states = InstallState(self.runner, ledger, self.paths).inspect(
            units, progress=self._inspect_progress)
        # warnings stream to the console too (errors already did, inline). These need `states`
        # (scope drift) so they land here at the end; the ! page / footer still collect them.
        for d in self.diagnostics(states):
            if d['level'] == 'warn':
                r.warn(d['text'])
        r.flush_transient()
        return cfg, requested, units, ledger, states

    def _inspect_progress(self, i, total, key, st, ms):
        '''Per-unit callback from InstallState.inspect: a transient counter at DEFAULT
        (so long state-checks show motion), a scrollable per-unit line at VERBOSE+.'''
        if self.reporter.level >= report.VERBOSE:
            self.reporter.event(report.VERBOSE,
                                f'  [{i}/{total}] {key}  {st.installed_version or "-"}  ({ms:.0f} ms)')
        else:
            self.reporter.status(f'checking install state… {i}/{total}')

    def _report_layers(self, routes):
        '''-v: the component layer stack that produced these routes, low→high precedence.'''
        r = self.reporter
        if r.level < report.VERBOSE:
            return
        r.event(report.VERBOSE, '  component layers (low → high precedence):')
        for lyr in routes.layers:
            r.event(report.VERBOSE, f'    · {lyr.role:9} {_layer_label(lyr.path, self.paths)}')

    def _report_routing(self, routes, requested):
        '''-v: components defined/redefined outside routes.hu (with provenance).
        -vv: the winning binding per requested component and the `when:` that selected it.'''
        r = self.reporter
        if r.level < report.VERBOSE:
            return
        overrides = sorted((c for c in routes.components.values()
                            if _layer_label(c.source, self.paths) != 'routes.hu'),
                           key=lambda c: c.name)
        if overrides:
            r.event(report.VERBOSE, f'  route overrides ({len(overrides)}):')
            for c in overrides:
                r.event(report.VERBOSE, f'    · {c.name:22} {_source_label(c, self.paths)}')
        if r.level < report.DEBUG:
            return
        from .resolve import select_binding, ResolveError
        cx = routes.cascade.context(routes.block, routes.version, routes.cpu)
        r.event(report.DEBUG, '  winning binding per requested component:')
        for name in sorted(requested):
            comp = routes.components.get(name)
            if comp is None:
                continue                                # a resolve error already reported this
            if not comp.bindings:
                r.event(report.DEBUG, f'    · {name:22} (removed / no binding)')
                continue
            try:
                b = select_binding(comp, routes.cascade, cx, routes.pins)
            except ResolveError:
                b = None
            if b is None:
                r.event(report.DEBUG, f'    · {name:22} (no binding matches here)')
            else:
                r.event(report.DEBUG,
                        f'    · {name:22} via {b.via:13} when: {b.when or "always"}')

    def report_session_summary(self, cfg, states, diags):
        '''Post-TUI recap printed to the console at -v+ (after endwin restores the terminal),
        so once a long session ends the OS, profiles, final state tally, and any issues persist
        in the scrollback where configsys was launched.'''
        r = self.reporter
        if r.level < report.VERBOSE:
            return
        ver = f' {self.os_info.version}' if self.os_info.version else ''
        r.event(report.VERBOSE, f'  session summary — {self.os_info.block}{ver}   '
                                f'profiles: {", ".join(cfg.active_profiles)}')
        tally = {}
        for st in states.values():
            tally[st.status] = tally.get(st.status, 0) + 1
        order = ('installed', 'outdated', 'missing', 'locked', 'unsupported', 'error')
        parts = [f'{tally[s]} {s}' for s in order if tally.get(s)]
        r.event(report.VERBOSE, f'    {len(states)} unit(s): ' + ', '.join(parts))
        if diags:
            r.event(report.VERBOSE, f'    {len(diags)} issue(s):')
            for d in diags:
                mark = '✗' if d['level'] == 'error' else '⚠'
                r.event(report.VERBOSE, f'      {mark} {d["tag"]:10} {d["text"]}')


# -- commands -------------------------------------------------------------

def cmd_inspect(ctx, args):
    _cfg, requested, units, _ledger, states = ctx.load_pipeline()
    print(f'OS: {ctx.os_info.block}   profiles: {", ".join(_cfg.active_profiles)}   '
          f'units: {len(units)}')
    if ctx.discovered:
        files = ', '.join(os.path.basename(d) for d in ctx.discovered)
        print(f'project: {os.path.dirname(ctx.discovered[0])}  ({files})')
    print()
    print(f'{"UNIT":30} {"STATUS":12} {"INSTALLED":20} {"LATEST"}')
    print('-' * 78)
    for key in sorted(states):
        s = states[key]
        lock = ' [locked]' if s.locked else ''
        print(f'{key:30} {_STATUS_LABEL.get(s.status, s.status):12} '
              f'{str(s.installed_version or "-"):20} {s.latest_version or "-"}{lock}')
    # non-fatal skips/warnings that would otherwise go unseen (dropped layers, quarantined
    # plugins, unroutable components, ...) — the same set the TUI shows on its `!` page.
    diags = ctx.diagnostics(states)
    if diags:
        print(f'\n{len(diags)} issue(s):')
        for d in diags:
            mark = '✗' if d['level'] == 'error' else '⚠'
            print(f'  {mark} {d["tag"]:12} {d["text"]}')
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
    last_failure = None
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
            last_failure = reportgen.failure_from_result(key, rc.driver, cur_op, res)
        else:
            print('  -> ok')
    if ledger is not None:
        ledger.save(ctx.paths)
    if last_failure is not None:
        _offer_report(ctx, last_failure)
    return rc_code


def _offer_report(ctx, failure):
    '''Persist the failure so `configsys report` can reuse it later, and — on a terminal —
    offer to file it now. Never fatal; a --pretend run doesn't reach here.'''
    reportgen.save_failure(ctx.paths, failure)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(f'\nconfigsys: {failure["unit"]} failed — run `configsys report '
              f'{failure["component"]}` to file a report.')
        return
    try:
        ans = input(f'\nfile a report of this {failure["component"]} failure? [y/N] ').strip().lower()
    except EOFError:
        ans = ''
    if ans in ('y', 'yes'):
        cmd_report(ctx, argparse.Namespace(name=failure['component'], yes=False, print_only=False))
    else:
        print(f'configsys: saved — `configsys report {failure["component"]}` files it later.')


def cmd_fix_scope(ctx, args):
    '''Reconcile installed units whose ACTUAL scope differs from their DECLARED scope — make the
    install match the config (never edits the config). No args = every mismatched active unit.'''
    _cfg, _req, _units, _ledger, states = ctx.load_pipeline()
    names = set(getattr(args, 'names', None) or [])
    fixed = failed = 0
    for key in sorted(states):
        st = states[key]
        rc = st.component
        if not st.present or not st.scope:
            continue
        if names and rc.comp not in names and key not in names:
            continue
        fam = get_driver(rc.driver, ctx.runner, ctx.paths)
        if fam is None or not fam.honors_scope:
            continue
        target = fam.scope(rc)
        if st.scope == target:
            continue                                  # already where it's declared
        print(f'fix-scope {key}: {st.scope} -> {target} ...')
        res = fam.reconcile_scope(rc, st.scope, target)
        if res.ok:
            print('  -> ok')
            fixed += 1
        else:
            print(f'  -> FAILED (exit {res.returncode})')
            failed += 1
    if not fixed and not failed:
        print('configsys: no scope mismatches to fix')
    return 1 if failed else 0


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
                 + list(ctx.plugin_files)                 # (path, role): 'primary' or 'plugin'
                 + [(d, 'discover') for d in ctx.discovered]
                 + [(ctx.paths.user_config_file, 'user')])
        layer_list, _w = layers.expand_tolerant(roots, {'discover', 'plugin', 'primary'})
    except ConfigsysError as e:
        print(f'configsys: {e}')          # a parse/structural error before we can lint
        return 1

    issues = routecheck.validate(components, cascade, drivers,
                                 pending_vias=ctx.plugin_pending_vias)
    include_warnings = layers.ignored_section_warnings(layer_list)

    # profile references: a selected profile naming a component that doesn't exist, plus
    # structural errors from expansion (undefined `+include`, include cycle).
    prof_issues = []
    prof_errors = []
    for prof in ctx.config.active_profiles:
        try:
            for cname in ctx.config.profile_components(prof):
                if cname not in components:
                    prof_issues.append((prof, cname))
        except ConfigsysError as e:
            prof_errors.append(str(e))

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

    from . import plugins as _plugins
    _top = _plugins.declared(ctx.paths.user_config_file)
    _decls = _plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
    # exactly one plugin may be `primary` (only the top config grants it)
    _primaries = [_plugins.dir_name(d['source']) for d in _top if d.get('primary')]
    if len(_primaries) > 1:
        prof_errors.append(f'multiple primary plugins declared: {", ".join(_primaries)} '
                           f'(only one may be primary)')
    conflict_warnings = [_fmt_conflict(*c) for c in
                         _plugins.declared_conflicts(ctx.paths.plugins_dir, _decls)]
    conflict_warnings += ctx.plugin_code_conflicts    # code-only (version-source/transport)
    conflict_warnings += [f"plugin {_plugins.dir_name(d['source'])}: content does not match "
                          f"declared sha256 — quarantined"
                          for d in _decls
                          if d.get('sha256') and not _plugins.checksum_ok(ctx.paths.plugins_dir, d)]

    errors = [i for i in issues if i.is_error]
    warnings = [i for i in issues if not i.is_error]
    code_warnings = ctx.plugin_code_warnings
    if (not errors and not warnings and not prof_issues and not prof_errors and not pin_issues
            and not include_warnings and not code_warnings and not conflict_warnings):
        print(f'configsys: OK — {len(components)} components, no issues')
        return 0

    for i in errors:
        print(f'  ERROR   {_issue_loc(i, ctx.paths)}{i.message}')
    for msg in prof_errors:
        print(f'  ERROR   {msg}')
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
    for msg in conflict_warnings:
        print(f'  warn    {msg}')
    n_err = len(errors) + len(prof_errors) + len(prof_issues) + len(pin_issues)
    n_warn = len(warnings) + len(include_warnings) + len(code_warnings) + len(conflict_warnings)
    print(f'\nconfigsys: {n_err} error(s), {n_warn} warning(s) '
          f'across {len(components)} components')
    return 1 if n_err else 0


# -- plugin: declare in `plugins:`, sync from git -------------------------

def _fmt_conflict(kind, name, dirs):
    return f"conflict: {kind} '{name}' claimed by plugins {', '.join(dirs)} (last declared wins)"


def _find_decl(decls, plugins_dir, ident):
    '''A declared plugin matching `ident` — its source, dir basename, or manifest name.'''
    from . import plugins
    for d in decls:
        dn = plugins.dir_name(d['source'])
        if ident in (d['source'], dn) or plugins.read_manifest(plugins_dir / dn).get('name') == ident:
            return d
    return None


def _locate_decl(ctx, ident):
    '''Find WHERE `ident` is declared — the top config, or a synced plugin's transitive
    `plugins:` (e.g. your primary) — and return (config_file, decls, target). This lets remove /
    update edit the file that actually declares the plugin, wherever it lives. The top config
    wins if a name somehow appears in more than one place. (None, None, None) if not found.'''
    from . import plugins
    pdir = ctx.paths.plugins_dir
    top = plugins.declared(ctx.paths.user_config_file)
    t = _find_decl(top, pdir, ident)
    if t is not None:
        return ctx.paths.user_config_file, top, t
    if pdir.exists():
        for sub in sorted(p for p in pdir.iterdir() if p.is_dir()):
            raw = plugins.read_manifest(sub).get('plugins') or []
            decls = [d for d in (plugins._decl(e) for e in raw) if d]
            t = _find_decl(decls, pdir, ident)
            if t is not None:
                return sub / 'plugin.hu', decls, t
    return None, None, None


def _sync_and_report(ctx, decls):
    from . import plugins
    ctx.ensure_plugin_code()     # register transports from already-trusted plugins before sync
    for name, action in plugins.sync(ctx.runner, ctx.paths.plugins_dir, decls):
        print(f'  {action:8} {name}')


def _bless_primary(ctx, ident):
    '''Make `ident` the sole `primary` plugin in the top config. Syncs it FIRST (the findability
    gate — "if it can find it"), pulling its transitive plugins too; only on success does it
    declare + mark primary (clearing any other primary). `ident` is a source
    (<provider>:<user>/<name>) or an already-declared plugin's name. Returns (ok, message).'''
    from . import plugins
    ctx.ensure_user_config()
    decls = plugins.declared(ctx.paths.user_config_file)
    existing = _find_decl(decls, ctx.paths.plugins_dir, ident)
    source = existing['source'] if existing else ident
    ref = existing.get('ref') if existing else None
    ctx.ensure_plugin_code()                         # register transports before sync
    results = plugins.sync(ctx.runner, ctx.paths.plugins_dir, [{'source': source, 'ref': ref}])
    for name, action in results:
        print(f'  {action:8} {name}')
    if not results or 'failed' in results[0][1].lower():
        return False, f"could not find/sync '{ident}' — nothing changed"
    if existing is None:
        existing = {'source': source, 'ref': ref}
        decls.append(existing)
    for d in decls:
        d.pop('primary', None)                       # exactly one primary
    existing['primary'] = True
    if ctx.runner.pretend:
        return True, f"[pretend] would bless {plugins.dir_name(source)} as primary"
    plugins.set_declared(ctx.paths.user_config_file, decls)
    return True, f"blessed {plugins.dir_name(source)} as primary (its machine settings now apply)"


def _upsert_decl(decls, source, ref):
    '''Add `source` to a decls list, or re-pin its ref if it's already there. Returns
    (target, existed) — the target dict is a live element of `decls`.'''
    target = next((d for d in decls if d['source'] == source), None)
    if target is not None:
        target['ref'] = ref
        return target, True
    target = {'source': source, 'ref': ref}
    decls.append(target)
    return target, False


def _pin_checksum(ctx, config_file, decls, target):
    '''Record the just-synced content hash of `target` as its `sha256` (a trust-on-first-use
    pin), so later syncs are verified against exactly this content. Writes back to `config_file`
    (the top config, or a primary plugin's plugin.hu when the add landed there).'''
    from . import plugins
    pdir = ctx.paths.plugins_dir / plugins.dir_name(target['source'])
    ident = plugins.plugin_identity(pdir)
    if ident is None:
        print('configsys: could not pin — plugin is not synced')
        return
    target['sha256'] = ident
    plugins.set_declared(config_file, decls)
    disp = plugins.read_manifest(pdir).get('name', plugins.dir_name(target['source']))
    print(f'configsys: pinned {disp} @ {ident.split(":")[-1][:12]} (sha256)')


def cmd_plugin(ctx, args):
    from . import plugins
    decls = plugins.declared(ctx.paths.user_config_file)   # top-config decls (for edits)
    # the full set incl. transitively-declared plugins (for read-only views + trust)
    eff = plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
    sub = getattr(args, 'plugin_command', None) or 'list'

    if sub == 'sync':
        if not decls:
            print('configsys: no plugins declared (add one: `configsys plugin add <source>`)')
            return 0
        _sync_and_report(ctx, decls)
        return 0

    if sub == 'bless':
        if args.source.lower() == 'none':
            return cmd_plugin(ctx, argparse.Namespace(plugin_command='unbless'))
        ok, msg = _bless_primary(ctx, args.source)
        print(f'configsys: {msg}')
        return 0 if ok else 1

    if sub == 'unbless':
        if not any(d.get('primary') for d in decls):
            print('configsys: no primary plugin set')
            return 0
        if ctx.runner.pretend:
            print('configsys: [pretend] would clear the primary designation')
            return 0
        for d in decls:
            d.pop('primary', None)
        plugins.set_declared(ctx.paths.user_config_file, decls)
        print('configsys: cleared the primary designation')
        return 0

    if sub == 'add':
        ctx.ensure_user_config()                    # the file must exist to edit it
        # With a primary plugin set, a new plugin rides IT — appended to the primary's transitive
        # `plugins:` — so it's portable to every machine that uses your primary. `--local` (or no
        # primary at all) pins it to this machine's top config instead. The primary is your own
        # synced repo, so this edits its on-disk clone; propagating to other machines still means
        # commit + push + re-tag the primary and bump its ref, same as any primary change.
        primary = plugins.primary_name(decls)
        primary_dir = ctx.paths.plugins_dir / primary if primary else None
        to_primary = (primary is not None and not getattr(args, 'local', False)
                      and primary_dir is not None and (primary_dir / 'plugin.hu').exists())
        if to_primary:
            cfg_file = primary_dir / 'plugin.hu'
            cur = [d for d in (plugins._decl(e) for e in
                               (plugins.read_manifest(primary_dir).get('plugins') or [])) if d]
        else:
            cfg_file, cur = ctx.paths.user_config_file, decls
        target, existing = _upsert_decl(cur, args.source, args.ref)
        plugins.set_declared(cfg_file, cur)
        verb, pin = ('re-pinned' if existing else 'added'), (f' @{args.ref}' if args.ref else '')
        if to_primary:
            print(f'configsys: {verb} {args.source}{pin} in the primary plugin ({primary})')
            print(f'configsys: it now rides {primary} to your other machines once you commit + '
                  f'push + re-tag {primary} and bump its ref (locally it works right away)')
        else:
            print(f'configsys: {verb} {args.source}{pin}'
                  + (' (this machine only)' if primary else ''))
        _sync_and_report(ctx, [target])
        if getattr(args, 'pin', False):
            _pin_checksum(ctx, cfg_file, cur, target)
        return 0

    if sub == 'remove':
        cfg_file, cur, target = _locate_decl(ctx, args.name)     # top config OR the plugin that declares it
        if target is None:
            print(f'configsys: no declared plugin matches {args.name!r}')
            return 1
        plugins.set_declared(cfg_file, [d for d in cur if d is not target])
        pdir = ctx.paths.plugins_dir / plugins.dir_name(target['source'])
        if pdir.exists() and not ctx.runner.pretend:
            import shutil
            shutil.rmtree(pdir)
        if cfg_file == ctx.paths.user_config_file:
            print(f'configsys: removed {target["source"]}')
        else:
            plug = cfg_file.parent.name
            print(f'configsys: removed {target["source"]} from {plug}')
            print(f'configsys: commit + push + re-tag {plug} and bump its ref to propagate the removal')
        return 0

    if sub == 'update':
        cfg_file, cur, target = _locate_decl(ctx, args.name)
        if target is None:
            print(f'configsys: no declared plugin matches {args.name!r}')
            return 1
        if args.ref:
            target['ref'] = args.ref
            plugins.set_declared(cfg_file, cur)
            where = '' if cfg_file == ctx.paths.user_config_file else f' in {cfg_file.parent.name}'
            print(f'configsys: re-pinned {target["source"]} @{args.ref}{where}')
        _sync_and_report(ctx, [target])
        if getattr(args, 'pin', False):
            _pin_checksum(ctx, cfg_file, cur, target)
        elif target.get('sha256') and not plugins.checksum_ok(ctx.paths.plugins_dir, target):
            print(f'configsys: warning — {plugins.dir_name(target["source"])} no longer matches '
                  f'its pinned sha256; it is quarantined until you re-pin (update --pin) or drop it')
        return 0

    if sub == 'trust':
        target = _find_decl(eff, ctx.paths.plugins_dir, args.name)   # incl. transitive plugins
        if target is None:
            print(f'configsys: no declared plugin matches {args.name!r}')
            return 1
        key = plugins.dir_name(target['source'])         # store key: stable across content
        pdir = ctx.paths.plugins_dir / key
        if not pdir.exists():
            print(f'configsys: {key} is not synced — run: configsys plugin sync')
            return 1
        manifest = plugins.read_manifest(pdir)
        disp = manifest.get('name', key)                  # friendly name for display
        if not manifest.get('code'):
            print(f'configsys: {disp} ships no code — nothing to trust')
            return 0
        identity = plugins.plugin_identity(pdir)
        if identity is None:
            print(f'configsys: could not read {disp}’s contents')
            return 1
        plugins.set_trust(ctx.paths.plugin_trust_file, key, identity)
        short = identity.split(':')[-1][:12]
        print(f'configsys: trusted {disp} @ {short} — its code will run during installs')
        return 0

    if sub == 'untrust':
        target = _find_decl(eff, ctx.paths.plugins_dir, args.name)
        key = plugins.dir_name(target['source']) if target else args.name
        pdir = ctx.paths.plugins_dir / key
        disp = plugins.read_manifest(pdir).get('name', key) if pdir.exists() else key
        if plugins.remove_trust(ctx.paths.plugin_trust_file, key):
            print(f'configsys: untrusted {disp}')
            return 0
        print(f'configsys: {disp} was not trusted')
        return 0

    if sub == 'list':
        rows = plugins.status(ctx.paths.plugins_dir, eff,
                              trust_file=ctx.paths.plugin_trust_file)
        if not rows:
            print('configsys: no plugins declared')
            return 0
        top = {plugins.dir_name(d['source']) for d in decls}
        for r in rows:
            if not r['synced']:
                state = 'not synced (run: configsys plugin sync)'
            elif r['checksum'] == 'mismatch':
                state = 'CHECKSUM MISMATCH — quarantined (content != declared sha256; re-pin or re-sync)'
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
            tags = ('  [primary]' if r['primary'] else
                    ('  [via primary]' if plugins.dir_name(r['source']) not in top else ''))
            print(f'  {r["name"]:22} {r["source"]}{ref}{tags}')
            print(f'  {"":22} {state}')
        for kind, name, dirs in plugins.declared_conflicts(ctx.paths.plugins_dir, eff):
            print(f'  {_fmt_conflict(kind, name, dirs)}')
        return 0

    print(f'configsys: unknown plugin subcommand {sub!r}')
    return 2


# -- report: file an install-failure report (no hidden telemetry) ---------

# Practical ceiling for a prefilled issues/new URL. GitHub's own docs cap the server at ~8k, and
# some browsers are tighter; 6k leaves headroom for encoding overhead and stays safely under both.
_URL_PREFILL_LIMIT = 6000


def _send_report(ctx, title, body):
    '''File the (already-approved) report. Prefer `gh issue create`; else save the body and
    print a prefilled new-issue link. Returns 0 on success/handed-off, 1 on failure.'''
    import shutil
    import subprocess
    import urllib.parse
    from .reportgen import REPORTS_REPO

    if shutil.which('gh'):
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False, encoding='utf-8') as f:
            f.write(body)
            bodyfile = f.name
        proc = subprocess.run(['gh', 'issue', 'create', '--repo', REPORTS_REPO,
                               '--title', title, '--body-file', bodyfile,
                               '--label', 'install-report'],
                              capture_output=True, text=True)
        if proc.returncode == 0:
            print(f'configsys: filed — {proc.stdout.strip()}')
            return 0
        print(f'configsys: gh could not file it ({proc.stderr.strip() or "error"}).')
        # fall through to the link path so the work isn't lost

    # no gh (or gh failed): save the body and print a prefilled new-issue link. When the body is
    # short enough to survive a URL, prefill it too so the browser opens fully populated; longer
    # ones fall back to open-the-link-and-paste (browsers/servers choke past ~8k of URL).
    out = ctx.paths.state_dir / 'last-report.md'
    try:
        ctx.paths.state_dir.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding='utf-8')
        saved = f'The full report is saved at {out}.'
    except OSError:
        saved = ''

    base = f'https://github.com/{REPORTS_REPO}/issues/new'
    fields = {'title': title, 'labels': 'install-report'}
    with_body = f'{base}?' + urllib.parse.urlencode({**fields, 'body': body})
    if len(with_body) <= _URL_PREFILL_LIMIT:
        print('configsys: no `gh` — open this and the issue is prefilled, ready to submit:\n'
              f'  {with_body}')
        if saved:
            print(f'({saved})')
    else:
        link = f'{base}?' + urllib.parse.urlencode(fields)
        print('configsys: install `gh` to file automatically, or open this and paste the body:\n'
              f'  {link}')
        if saved:
            print(saved)
    return 0


def cmd_report(ctx, args):
    from . import reportgen
    saved = reportgen.load_failure(ctx.paths)
    name = getattr(args, 'name', None) or (saved or {}).get('component')
    if name is None:
        print('configsys: nothing to report — name a component (`configsys report <name>`) '
              'or run it after a failed install so the failure is captured.')
        return 1
    # only attach the saved failure if it's about the component we're reporting
    failure = saved if saved and saved.get('component') == name else None

    payload = reportgen.collect(ctx, component=name, failure=failure)
    secrets = reportgen.secret_values(ctx.env)
    body = reportgen.render(payload, home=ctx.paths.home, secrets=secrets)
    title = reportgen.title(payload)

    print('\n' + '=' * 72)
    print(f'{title}\n')
    print(body)
    print('=' * 72)
    if not failure:
        print('note: no captured driver output (report either after a failed op, or paste it in).')
    if getattr(args, 'print_only', False):
        return 0

    if not getattr(args, 'yes', False):
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print('\nconfigsys: not a terminal; re-run with --yes to file, or --print to just view.')
            return 1
        try:
            ans = input(f'\nSend this report to {reportgen.REPORTS_REPO}? [y/N] ').strip().lower()
        except EOFError:
            ans = ''
        if ans not in ('y', 'yes'):
            print('configsys: not sent.')
            return 0
    return _send_report(ctx, title, body)


# -- argument parsing -----------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(prog='configsys',
                                description='Sync OS-native software from a profile.')
    p.add_argument('--pretend', action='store_true',
                   help='print commands instead of executing them (dry run)')
    p.add_argument('--os', help='override detected OS routes block (e.g. pop_os!)')
    p.add_argument('--home', help='override HOME base for all paths (sandboxing)')
    p.add_argument('--config', help='override the per-machine selector file path')
    p.add_argument('-v', '--verbose', action='count', default=0,
                   help='stream load detail to stderr: -v layers/overrides/per-unit state, '
                        '-vv full route/binding/why (errors + progress already show by default)')
    p.add_argument('-q', '--silent', action='store_true',
                   help='no console output during load at all — only the TUI ! page')

    sub = p.add_subparsers(dest='command')
    sub.add_parser('inspect', help='show install state of the active profiles')

    for name, help_ in (('install', 'install components'),
                        ('remove', 'uninstall components'),
                        ('upgrade', 'upgrade components to latest'),
                        ('lock', 'version-lock components'),
                        ('unlock', 'remove version lock')):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument('names', nargs='+', help='component names (from a profile/routes)')

    fs = sub.add_parser('fix-scope', help='reconcile installed units whose actual scope differs '
                                          'from the declared scope (moves the install, not config)')
    fs.add_argument('names', nargs='*', help='component names (default: all mismatched)')

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
    pb = plsub.add_parser('bless', help='designate your primary personal-config plugin '
                                        '(register + sync it; its machine settings then apply)')
    pb.add_argument('source', help='<provider>:<user>/<name> (or a declared plugin name), or '
                                   '"none" to clear')
    plsub.add_parser('unbless', help='clear the primary designation')
    pa = plsub.add_parser('add', help='declare a plugin and sync it')
    pa.add_argument('source', help='github:owner/repo | gitlab:owner/repo | git URL | local path')
    pa.add_argument('--ref', help='pin to a tag / commit / branch')
    pa.add_argument('--pin', action='store_true',
                    help='also lock the plugin to the synced content hash (sha256)')
    pa.add_argument('--local', action='store_true',
                    help='add to this machine\'s top config even if a primary plugin is set '
                         '(default: a new plugin rides the primary, portable to all machines)')
    pr = plsub.add_parser('remove', help='undeclare a plugin and delete its synced copy')
    pr.add_argument('name', help='plugin name, source, or dir')
    pu = plsub.add_parser('update', help="re-sync a plugin (move its pin with --ref)")
    pu.add_argument('name', help='plugin name, source, or dir')
    pu.add_argument('--ref', help='new tag / commit / branch to pin to')
    pu.add_argument('--pin', action='store_true', help='re-lock to the new synced content hash')
    pt = plsub.add_parser('trust', help="approve a code plugin's current content to run during installs")
    pt.add_argument('name', help='plugin name, source, or dir')
    pun = plsub.add_parser('untrust', help="revoke a code plugin's trust")
    pun.add_argument('name', help='plugin name, source, or dir')

    rp = sub.add_parser('report', help='assemble an install-failure report (OS + route + driver '
                                       'output) and file it upstream — you approve the full text first')
    rp.add_argument('name', nargs='?', help='component (defaults to the last failed op)')
    rp.add_argument('--yes', action='store_true', help='skip the send confirmation (still shows it)')
    rp.add_argument('--print', dest='print_only', action='store_true',
                    help='print the report and exit; never send')

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
    'fix-scope': cmd_fix_scope,
    'where': cmd_where,
    'check': cmd_check,
    'plugin': cmd_plugin,
    'refresh': cmd_refresh,
    'report': cmd_report,
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
