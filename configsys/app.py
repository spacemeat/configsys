'''app.py — the app itself: the Context and `main`.

The Context wires the pipeline every command and the TUI share: detect the OS -> load the layered
config + routes -> resolve this machine's picks to units -> inspect live state. `main` parses the
command line and dispatches a verb to its module in configsys/cli/ (or opens the TUI — the default).
All shell-outs honor --pretend; path/OS overrides make runs fully sandboxable for tests and
containers. Every name that moved to configsys/cli/ (review-2026-11-2 D2) is re-exported here, so
`configsys.app.<name>` keeps resolving for plugins, scripts and tests.
'''

import os
import sys

from . import osdetect
from . import report
from . import primarygit
from .config import Config
from .errors import ConfigsysError
from .drivers import get_driver
from .installState import InstallState
from .ledger import Ledger
from .paths import Paths
from .routes import Resolver
from .runner import Runner


def _unskip(w):
    '''Drop a leading "skipped " tag from a load-warning for clean display.'''
    return w[len('skipped '):] if w.startswith('skipped ') else w

USER_CONFIG_TEMPLATE = '''{
    // configsys — this machine's settings and overrides. Overlays the repo's
    // config.hu + routes.hu section by section (your definitions win).

    // Pull in other files. An included file may define anything this file can (components,
    // profiles, os/drivers blocks); only machine settings like picks:, pins: and scope: are
    // ignored there. Relative paths resolve against THIS file's directory.
    // include: [ ~/src/myproject/configsys.hu ]

    // Data plugins from git repos, pinned to a ref, then `configsys plugin sync`. A
    // github:/gitlab: source has a colon so it must be quoted.
    // plugins: [ { source: "github:someone/configsys-opensuse"  ref: v1.2.0 } ]

    // The install set is per-machine `picks:` — the components tracked on this box. Browse the
    // shipped profile catalog in the TUI (or `configsys profile list`) and track what you want;
    // edits land here. A one-machine user can omit the machine key (defaults to `this-machine`).
    // picks: { this-machine: [ btop  ripgrep  neovim ] }

    // Machine-wide default install scope for scope-honoring drivers (user | system).
    // scope: system

    // Pins — the light way to reroute without redefining a component:
    //   component -> driver  (binding-pin: force a method)
    //   capability -> component  (provider-pin: force who satisfies a requirement)
    // pins: {
    //     steam: flatpak
    // }

    // TUI theme (all optional; edit live on the Theme screen, key 7). `colors:` is a shared MAP of
    // name -> #rrggbb; `pages:` gives each screen's ROLES a style { fg  bg  bold  underline
    // reverse } where fg/bg name a map color OR are a literal "#rrggbb", plus that page's background
    // `gradient:` (24-bit terminals only; `gradient: false` turns it off). A role defaults to a
    // built-in style, so a page spells out only what differs. See docs/theming.md for the roles.
    // `colors-basic:` pins the SAME map names to an ANSI slot (a color name, `bright-<name>`, 0..15,
    // or `default`) for the 8/16-color path only — the built-ins are hand-tuned; override to taste.
    // theme: {
    //     colors: { accent: "#c88cf0"  ink: "#dcdcdc"  ink_dim: "#9a9a9a" }
    //     colors-basic: { accent: bright-magenta  error: bright-red  installed: green }
    //     pages: {
    //         components: { component: { fg: ink }              // fg references the map
    //                       driver:    { fg: ink_dim }
    //                       selection: { fg: "#ffffff"  bg: accent  bold: true }
    //                       gradient:  { from: "#160a22"  to: "#050208" } }
    //         profiles:   { gradient: { from: "#08221e"  to: "#020806" } }   // just a different bg
    //     }
    // }

    // Your own browse categories (they never install anything — `picks:` does). A profile is a
    // list of components and `+other-profile` includes; same name as a shipped one replaces it,
    // and `+<its own name>` first amends it instead.
    // profiles: { my-favorites: [ btop  ripgrep  +file-browsers ] }

    // Override component routes: bindings merge ADDITIVELY — add an install method (or your
    // own component), override a binding by its (via, when), `drop:` one, or {} to remove the
    // whole component. To just pick an existing method, prefer a pin (above). See routes.hu.
    // components: {
    //     my-cli: { install: [ { via: native } ] }              // add your own
    //     steam:  { install: [ { via: native  when: "pop_os!"  drop: true } ] }  // drop a binding
    //     apod:   {}                                            // remove entirely
    // }
}
'''


class Context:
    def __init__(self, args):
        env = dict(os.environ)
        if args.home:
            # a FULL sandbox (§7 default): nothing inherited points configsys back at the real home —
            # an exported CONFIGSYS_STATE_DIR / CONFIGSYS_CONFIG / XDG_*_HOME would otherwise win
            for k in ('CONFIGSYS_STATE_DIR', 'CONFIGSYS_CONFIG', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME',
                      'XDG_CACHE_HOME', 'XDG_STATE_HOME'):
                env.pop(k, None)
            env['CONFIGSYS_HOME'] = args.home
        if args.os:
            env['CONFIGSYS_OS'] = args.os
            env.pop('CONFIGSYS_OS_VERSION', None)   # the flag replaces the env pair: BLOCK[:VERSION]
        if args.config:
            env['CONFIGSYS_CONFIG'] = args.config
        if getattr(args, 'splash_linger', False):
            env['CONFIGSYS_SPLASH'] = 'linger'      # force + hold the splash until a keypress
        self.env = env
        self.paths = Paths(env)
        self.os_info = osdetect.detect(env)
        level = report.SILENT if getattr(args, 'silent', False) \
            else min(getattr(args, 'verbose', 0), report.DEBUG)
        self.reporter = report.Reporter(level)
        self.runner = Runner(pretend=args.pretend, echo=lambda m: print(m),
                             sandbox_home=self.paths.home if args.home else None)
        self._config = None
        self._routes = None            # cached Resolver (rebuilding it = parse routes.hu + routecheck)
        self._os_refined = False       # detect:-marker refinement runs once, lazily
        self.os_note = None            # osdetect.settle's fallback note (an ID_LIKE stand-in block)
        self._plugin_files = None
        self._plugin_code_loaded = False
        self.plugin_code_warnings = []   # code plugins that ship code but were gated out
        self.plugin_code_conflicts = []  # code-level registration collisions (version-source/transport)
        self.plugin_pending_vias = set()  # via names those gated-out plugins would provide
        self.resolve_errors = {}      # {requested_name: message} from the last resilient resolve
        self.route_classes = {}       # {requested_name: ('dangling'|'unmet', detail)} (stranded.py)
        # working-TARGET machine: `--machine X` curates/plans machine X's set from any box (overrides
        # the local `machine:` setting for this run). None -> use the box's own `machine:` selection.
        self.machine_override = getattr(args, 'machine', None) or None
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
            if self.runner.pretend:
                # a dry run moves nothing: READ the legacy file in place for this run (every config
                # write is refused under --pretend, so nothing can land in it), and say so
                print(f'configsys: [pretend] would move {legacy} -> {new} (reading it in place)')
                self.paths.user_config_file = legacy
                return
            new.parent.mkdir(parents=True, exist_ok=True)
            legacy.rename(new)
            print(f'configsys: moved {legacy} -> {new}')

    def _cpu(self):
        '''System CPU arch for routing ($ARCH assets, cpu: when-atoms).'''
        import platform
        return self.env.get('CONFIGSYS_ARCH') or platform.machine()

    def diagnostics(self, states=None):
        '''Every non-fatal skip/warning from loading + resolution, as {level, tag, text} (deduped
        by text). This is the "silent stuff" — a malformed layer that got dropped (the exact class
        that can make a whole primary plugin vanish), a plugin quarantined / untrusted / ABI-
        incompatible, a machine-setting section ignored from a non-primary plugin, a requested
        component that can't route here. With `states`, also flags scope mismatches (installed at
        a different scope than the config declares — `fix-scope` reconciles them). Surfaced by the
        TUI (! page) and inspect. Call after a load so config/routes/resolve_errors are populated.
        Memoized on (states, config, routes): `inspect` used to compute it twice — each re-resolving
        the picks and re-hashing every plugin (C3 / app-cli-11).'''
        key = (id(states), id(self._config), id(self._routes))
        hit = getattr(self, '_diag_memo', None)
        if hit is not None and hit[0] == key and hit[1] is states:
            return [dict(d) for d in hit[2]]
        out = self._diagnostics(states)
        self._diag_memo = (key, states, out)
        return [dict(d) for d in out]

    def _diagnostics(self, states=None):
        from . import layers, plugins
        out, seen = [], set()

        def add(level, tag, text):
            if text and text not in seen:
                seen.add(text)
                out.append({'level': level, 'tag': tag, 'text': text})

        if osdetect.is_atomic(self.os_info.block):
            add('warn', 'atomic',
                'atomic/immutable OS detected — configsys atomic routing is NEW and not yet '
                'validated on real hardware. Here CLI tools install via Homebrew, apps via '
                'Flatpak, and `via: rpm-ostree` layering is reboot-gated. Dev toolchains, the '
                'GPU/Vulkan stack, docker and AppImages are NOT managed here — use distrobox, '
                'podman, or rpm-ostree for those. Review the plan before you run any op, and '
                'please report anything that misroutes.')

        if self.os_note:
            add('warn', 'os', self.os_note)
        try:                                             # an os: block's caveat, inherited via `using:`
            add('warn', 'os-advisory', self.routes.cascade.advisory(self.os_info.block))
        except (ConfigsysError, KeyError):               # a block not loaded yet: check_os says so
            pass
        self.ensure_plugin_code()                        # populates plugin_code_warnings
        for w in getattr(self.config, 'load_warnings', []):
            add('error', 'skipped', _unskip(w))          # a dropped config layer (primary/plugin)
        for w in getattr(self.routes, 'load_warnings', []):
            add('error', 'skipped', _unskip(w))          # a dropped routes layer or component
        if Ledger.load(self.paths).corrupt is not None:   # B10: read as empty; moved aside on next save
            add('error', 'ledger',
                f'{self.paths.ledger_file} is unreadable — configsys is running without its locks and '
                'install receipts; the next save keeps the bad file as state.hu.corrupt-<time>')
        for bundle, parts in sorted((getattr(self.routes, 'skipped_parts', None) or {}).items()):
            for part, why in parts:                      # B15: a bundle installs the parts that route here
                add('warn', 'part-skipped', f'{bundle}: part {part} skipped here — {why}')
        for w in layers.duplicate_key_warnings(getattr(self.config, '_layers', [])):
            add('warn', 'duplicate-key', w)
        for w in self.config.ignored_section_warnings():
            add('warn', 'ignored', w)
        for w in self.config.unknown_section_warnings():
            add('warn', 'unknown-key', w)
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
        if states:
            from . import stranded
            for level, tag, text in stranded.diagnostics(states):
                add(level, tag, text)
        else:
            for name, (status, detail) in sorted((getattr(self, 'route_classes', None) or {}).items()):
                add('warn', status, f'{name}: {detail}')
        for key, st in sorted((states or {}).items()):
            if not (st.present and st.scope):
                continue
            drv = get_driver(st.component.driver, self.runner, self.paths)
            if drv is not None and drv.honors_scope:
                target = drv.scope(st.component)
                if st.scope != target:
                    add('warn', 'scope', f"{key}: installed {st.scope}, config declares "
                                         f"{target} — run: configsys fix-scope")
        if states:
            # floor advisories (stage 3, surface-and-choose): a resolved unit whose provider's
            # default method can't meet a version floor. A no-op unless floors are active, so it
            # adds no cost until the version-floors data exists.
            from . import flooradvise
            comps = [st.component for st in states.values()]
            for adv in flooradvise.advise(self, comps):
                add(adv['level'], adv['tag'], adv['text'])
            # resident floors: a toolchain that's INSTALLED but too old for a consumer (the gap the
            # method-based advisory misses — e.g. resident go 1.18 for a go>=1.21 consumer).
            for adv in flooradvise.resident_advise(self, comps, states):
                add(adv['level'], adv['tag'], adv['text'])
            # dotfiles hygiene (warn-only): un-captured managed config + any surviving repo-link.
            for tag, text in _dotfiles_diagnostics(self):
                add('warn', tag, text)
        for note in getattr(self, '_sysupd_notes', None) or ():   # the TUI's System Updates scan
            add('warn', 'system-updates', note)
        for text in _failure_diagnostics(self, states):
            add('error', 'failed', text)
        for level, text in getattr(self, '_check_rows', None) or ():   # `check`'s lints (G2), once
            bare = text[len('skipped '):] if text.startswith('skipped ') else text   # the pass landed
            if bare not in seen:                         # (what the page already says, once)
                add(level, 'check', text)
        return out

    def start_check_lints(self):
        '''Run `check`'s lints (check_report) on a daemon thread; when they land they join the `!`
        page (diagnostics) and `_check_dirty` tells the TUI to recompute it (review-2026-11-2 G2 —
        plugin conflicts, driver shadowing, key lockouts, setting values … were check-only). A
        failure just leaves the page as it was.'''
        import threading
        self._check_dirty = False

        def work():
            try:
                rows, _n = check_report(self)
            except Exception:                            # noqa: BLE001 — a lint never breaks the TUI
                return
            self._check_rows = rows
            self._diag_memo = None
            self._check_dirty = True
        t = threading.Thread(target=work, name='configsys-check', daemon=True)
        self._check_thread = t
        t.start()

    def check_busy(self):
        t = getattr(self, '_check_thread', None)
        return bool(t is not None and (t.is_alive() or getattr(self, '_check_dirty', False)))

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
        # point the dotfiles driver at the primary plugin's content store (capture's default home,
        # and a read root that shadows any shipped template) — only if it's actually synced.
        prim = plugins.primary_name(decls)
        pdir = self.paths.plugins_dir / prim / 'dotfiles' if prim else None
        self.paths.primary_dotfiles_dir = pdir if (pdir is not None and pdir.exists()) else None
        gdir = self.paths.plugins_dir / prim / 'glue' if prim else None
        self.paths.primary_glue_dir = gdir if (gdir is not None and gdir.exists()) else None
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

    def _resolver(self, block):
        # layer stack: routes.hu < plugin data files < ~/configsys.hu (components overlay + pins).
        # A malformed plugin file is skipped, not fatal.
        self.ensure_plugin_code()     # register trusted plugin drivers before `via:` resolves
        from . import predicate
        memo = getattr(self.paths, 'grid_memo_file', None)
        if memo is not None and not getattr(self, '_memo_loaded', False):
            predicate.load_memo(memo)                   # the when-grid answers of earlier runs (C3)
            self._memo_loaded = True
        r = self._new_resolver(block)
        if memo is not None and not self.runner.pretend:
            predicate.save_memo(memo)                   # (a cache: never written under --pretend)
        return r

    def _new_resolver(self, block):
        from . import plugins
        return Resolver(self.paths.routes_file, block,
                        self.os_info.version, self._cpu(),
                        pins=self.config.pins(),
                        overrides_path=self.paths.user_config_file,
                        plugin_files=self.plugin_files,
                        preference=self.config.driver_preference(),
                        disabled=self.config.disabled_drivers(),
                        # facets are command-carrying data: a plugin's merge only if it's trusted
                        command_trust=lambda p: plugins.command_source_trusted(self.paths, p))

    @property
    def routes(self):
        # MEMOIZED: building a Resolver = parse routes.hu + all layers + routecheck (~150ms), and
        # callers hit this property hundreds of times (the Profiles catalog resolves every component
        # via `ctx.routes.candidates`). Cache it; `invalidate()` clears the cache on any in-process
        # write (a pin, a config/profile edit, a plugin sync/trust — all route through invalidate),
        # so the cached Resolver never goes stale.
        if self._routes is not None:
            return self._routes
        r = self._resolver(self.os_info.block)
        # Once the cascade is loaded (with plugin os blocks), refine the block via `detect:`
        # markers — e.g. an ID=debian host with /etc/pve is really `proxmox`. Runs once; only
        # rebuilds when a marker actually reroutes (rare).
        if not self._os_refined:
            self._os_refined = True
            block = self.os_info.block
            if not self.os_info.forced:   # a forced block may arrive with a plugin (check_os)
                self.os_note = osdetect.settle(self.os_info, r.cascade.blocks) or self.os_note
            refined = osdetect.refine(self.os_info.block, r.cascade, self.env)
            self.os_info.block = refined
            if refined != block:
                r = self._resolver(refined)
        self._routes = r
        return r

    def check_os(self, *, light=False):
        '''Raise ConfigsysError unless the OS block (a forced one included) names a loaded os: block.
        `light` (a command that never reads the catalog — `show`, `keys`, `manpages`) vets it against
        the os: sections alone: building and route-checking the whole catalog just to check a block
        name was most of such a command (app-cli-20). Every other command builds the Resolver here,
        on the main thread, as before (the TUI's worker then reuses it).'''
        if light and self._routes is None:
            from .routes import os_blocks
            blocks = os_blocks(self.paths.routes_file, self.paths.user_config_file, self.plugin_files)
        else:
            blocks = self.routes.cascade.blocks
        osdetect.settle(self.os_info, blocks)

    @property
    def config(self):
        if self._config is None:
            self._config = Config.load(self.paths, self.plugin_files, machine=self.machine_override)
            # back the built-in `all` profile with the loaded component set (lazy: routes carry it)
            self._config._universe_provider = lambda: set(self.routes.components)
            self.paths.set_config_dirs(self._config.install_dirs())   # env still overrides these
        return self._config

    def invalidate(self):
        '''Drop cached state so the next access rebuilds it — after an in-process write. Config
        edits (a pin, a profile toggle) need only the config reread; a plugin add/sync/trust also
        changes what's on disk, so we also drop the plugin data-file layer and the once-only code
        load. That way newly-available components, install methods, and plugin DRIVERS (e.g.
        opencv-build) show up across the TUI without a restart — dropping the cached Resolver forces
        the next `routes` access to rebuild it from the new layers + drivers.
        Cheap: for the common no-plugin case the code reload loops over nothing.'''
        self._config = None
        self._diag_memo = None
        self._routes = None              # drop the cached Resolver; next access rebuilds it
        self._plugin_files = None        # re-glob declared+synced plugin data layers
        self._plugin_code_loaded = False  # re-register trusted plugin drivers (idempotent overwrite)
        self._os_refined = False          # a plugin may add a derivative-distro os block w/ a detect: marker

    def invalidate_config(self):
        '''Drop only the merged Config — for an edit to a section the Resolver never reads (picks,
        dispositions, the uninstall queue, orphans-ignore, the machine registry). The cached
        Resolver (and every screen cache keyed on it) survives, so a Profiles triage key costs
        milliseconds, not a 0.5 s Resolver rebuild and a cold catalog (review-2026-11-2 C2).'''
        self._config = None
        self._diag_memo = None

    def apply_scope_default(self, units):
        '''Stamp the machine-wide scope default onto units whose driver *honors*
        scope and that don't set `scope` in their route (component field wins). Apt
        (always system) and cargo/dotfiles (per-user) are left alone.'''
        default = self.config.default_scope()
        if default:
            for rc in units.values():
                drv = get_driver(rc.driver, self.runner, self.paths)
                if drv is not None and drv.honors_scope:
                    rc.fields.setdefault('scope', default)
        return units

    def apply_locations(self, units):
        '''Stamp the per-component install-location override (config `locations:`) onto matching
        units as the reserved `location` field, so a path-based driver finds/manages the install
        where the user put it. Keyed by component name; a route field named `location` is left
        alone (the config override only fills, never clobbers an explicit binding value).'''
        locs = self.config.locations()
        if locs:
            for rc in units.values():
                if rc.comp in locs:
                    rc.fields.setdefault('location-override', locs[rc.comp])
        return units

    def own_machine(self):
        '''THIS box's machine name (its `machine:` setting, else `this-machine`) — never `--machine`.'''
        return self.config.configured_machine() or 'this-machine'

    def curating_machine(self):
        '''The OTHER machine `--machine` names, when it isn't this box — you are curating its picks
        from here, and installs never happen for another machine here (CLI `--picks` refuses, the TUI
        Components screen is read-only) — else None.'''
        m = getattr(self, 'machine_override', None)
        return m if m and m != self.own_machine() else None

    def prepare_units(self, units):
        '''Stamp BOTH the scope default and the `locations:` override onto freshly-resolved units —
        the single preparation every code path must run before handing units to a driver (inspect,
        install/remove/upgrade/lock, `location`). Calling only one (as the CLI op path historically
        did) makes a relocated component install/report at the wrong dir. No surprises.'''
        self.apply_scope_default(units)
        self.apply_locations(units)
        self.apply_native(units)
        return units

    def apply_native(self, units):
        '''Stamp this machine's native package manager (the OS block's `native:`) onto every unit, so
        a driver that installs through it (native-pkg-file, the gcc/clang alternatives) follows the
        resolved OS — `--os` included — instead of sniffing the host's binaries (B14).'''
        try:
            mgr = self.routes.cascade.native(self.os_info.block) or ''
        except Exception:                                # noqa: BLE001 — no routes yet: drivers fall back
            mgr = ''
        for rc in units.values():
            if not rc.native:
                rc.native = mgr
        return units

    def ensure_user_config(self, *, offer_primary=False):
        p = self.paths.user_config_file
        if p.exists():
            return
        if self.runner.pretend:
            # a dry run writes nothing. The template is comments only, so an ABSENT file loads to
            # the identical default config (layers skip a missing root); every config write is
            # refused under --pretend (actions.PRETEND_NOT_SAVED), so nothing needs the file.
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
        print('\nYour personal config (picks, scope, pins) can live in a "primary" plugin so')
        print("it travels with you. Point configsys at yours now, or press Enter to skip.")
        try:
            ans = input('  primary plugin  <provider>:<user>/<name>  [none]: ').strip()
        except EOFError:
            return
        if not ans or ans.lower() == 'none':
            return
        from . import actions
        _ok, msg, results = actions.plugin_bless(self, ans)
        _print_sync(self, results)
        print(f'configsys: {msg}')

    def load_pipeline(self, reuse=None, dirty=None, progress=None, detect_progress=None,
                      batch_progress=None):
        r = self.reporter
        # the detection passes' probe cache: a full load starts FRESH (it must see the machine as it
        # is); a reload that reuses inspection keeps it, dropping only what its dirty units touched
        from .probecache import ProbeCache
        if reuse is None or getattr(self, '_probes', None) is None:
            self._probes = ProbeCache()
        else:
            self._probes.invalidate(dirty)
        # never the first-run primary offer: that is the TUI's (tui/menu.run, on the main thread before
        # curses) — a pipeline command (inspect, refresh, install --picks) doesn't stop to ask (app-cli-32)
        self.ensure_user_config()
        cfg = self.config
        r.event(report.VERBOSE, f'  config: install set — {_install_scope_label(cfg)}')
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
        units, self.resolve_errors = routes.resolve_resilient(list(requested), record=True)
        tighten = {}
        if cfg.auto_tighten():
            # opt-in: auto-select a floor-satisfying method for a provider whose default is too old
            # (fresh installs only — a replacement of an installed provider stays advisory).
            from . import flooradvise
            tighten = flooradvise.tighten_pins(self, list(units.values())) or {}
        detected = {}
        if cfg.adopt_installed() and not self.runner.pretend:
            # the detection tier: bias toward what's already installed (soft — below your pins).
            # Skipped under --pretend (probing the disk there is meaningless / non-deterministic).
            from . import detection
            detected = detection.detect_pins(self, units, progress=detect_progress) or {}
        if tighten or detected:
            units, self.resolve_errors = routes.resolve_resilient(
                list(requested), extra_pins=(tighten or None), soft_pins=(detected or None),
                record=True)
            for prov, via in sorted(tighten.items()):
                r.event(report.DEFAULT, f'  auto-tightened {prov} -> via {via} '
                                        f'(to meet a version floor)')
            dropped = getattr(routes, 'dropped_soft_pins', None) or {}
            for what, choice in sorted(detected.items()):
                if what in dropped:          # a detected install that fails a version need: not adopted
                    r.event(report.VERBOSE, f'  not adopting installed {what} -> {choice}: {dropped[what]}')
                else:
                    r.event(report.DEFAULT, f'  adopting installed: {what} -> {choice}')
        # picks with no install method valid here (dangling) or only a disabled driver's (unmet)
        # are a ROUTING STATUS, not an error: they get a row (+ any stranded install) below
        from . import stranded
        self.route_classes = stranded.classify_unroutable(self, list(self.resolve_errors or {}))
        for name in self.route_classes:
            self.resolve_errors.pop(name, None)
        for name in sorted(self.resolve_errors or {}):
            r.error(f'{name}: {self.resolve_errors[name]}')
        r.event(report.VERBOSE, f'  resolved {len(requested)} requested -> {len(units)} unit(s)')
        self._report_routing(routes, requested)         # -v overrides, -vv winning binding + why
        self.prepare_units(units)
        # the resolution this session actually installs from — consumers that need the units
        # (dotfiles_units) reuse it instead of a pin-less re-resolve (B17 / actions-13)
        self.pipeline_units = (id(routes), id(cfg), units)
        ledger = Ledger.load(self.paths)
        inspector = InstallState(self.runner, ledger, self.paths,
                                 pending_vias=self.plugin_pending_vias)
        states = inspector.inspect(
            units, progress=(progress or self._inspect_progress), reuse=reuse, dirty=dirty,
            batch_progress=batch_progress)
        # hand the batched drivers' installed enumeration to later consumers (the TUI install
        # overlay seeds its per-driver cache from this, so the first `O` doesn't re-list).
        self.startup_enum = getattr(inspector, 'enum', {})
        if cfg.detect_coexisting():
            from .installState import detect_coexisting     # "also present (unmanaged)" per component
            detect_coexisting(self, states)
        # stranded installs (always — a safety check, not a preference): a component still
        # installed via a method routes no longer offer here reads `switch`; dangling/unmet picks
        # get rows. Under --pretend the probes would be pretend reads, so skip it there.
        if not self.runner.pretend:
            stranded.augment(self, states, ledger, cache=self._probes)
        states.update(stranded.unroutable_states(
            self, self.route_classes, ledger, cache=(None if self.runner.pretend else self._probes)))
        # warnings stream to the console too (errors already did, inline). These need `states`
        # (scope drift) so they land here at the end; the ! page / footer still collect them. Not on a
        # TUI reload (reuse=): the TUI computes its own diagnostics, and this pass costs ~1s.
        if reuse is None:
            for d in self.diagnostics(states):
                if d['level'] == 'warn':
                    r.warn(d['text'])
        r.flush_transient()
        return cfg, requested, units, ledger, states

    def inspect_components(self, names, reuse=None):
        '''Resolve + inspect component `names` that live OUTSIDE the active set — the `!uninstall`
        queue's orphans — returning {unit_key: ComponentState} so TUI::Components can list and remove
        them. Same scope/location/inspect path as load_pipeline, minus the reporting. {} if none route.

        Only the units that ARE the named components are returned, NOT the requires-closure they pull
        in: uninstalling `conan` means removing the conan unit (pipx\\conan), never its shared deps
        (pipx, bash-dotfiles, …) — surfacing those would let a "mark all" nuke infrastructure other
        components still need.'''
        from .installState import InstallState
        from .ledger import Ledger
        units, _errs = self.routes.resolve_resilient(list(names))
        wanted = set(names)
        units = {k: rc for k, rc in units.items() if rc.comp in wanted}
        if not units:
            return {}
        self.prepare_units(units)
        return InstallState(self.runner, Ledger.load(self.paths), self.paths,
                            pending_vias=self.plugin_pending_vias).inspect(units, reuse=reuse)

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
        from .resolve import ResolveError
        cx = routes.context()
        r.event(report.DEBUG, '  winning binding per requested component:')
        for name in sorted(requested):
            comp = routes.components.get(name)
            if comp is None:
                continue                                # a resolve error already reported this
            if not comp.bindings:
                r.event(report.DEBUG, f'    · {name:22} (removed / no binding)')
                continue
            try:
                b = routes.select(comp, context=cx).binding
            except ResolveError:
                b = None
            if b is None:
                r.event(report.DEBUG, f'    · {name:22} (no binding matches here)')
            else:
                r.event(report.DEBUG,
                        f'    · {name:22} via {b.via:13} when: {b.when or "always"}')

    def report_session_summary(self, cfg, states, diags):
        '''Post-TUI recap printed to the console (after endwin restores the terminal), so once a long
        session ends its outcome persists in the scrollback where configsys was launched. Any ISSUES
        (errors + warnings — the ! page's contents) ALWAYS print, so a broken config is never silently
        swallowed just because you ran the TUI and quit; the OS/profiles/state-tally recap stays -v+.'''
        r = self.reporter
        if r.level < report.VERBOSE:
            if diags:
                n_err = sum(1 for d in diags if d['level'] == 'error')
                bits = ([f'{n_err} error(s)'] if n_err else []) + \
                       ([f'{len(diags) - n_err} warning(s)'] if len(diags) - n_err else [])
                print(f'\nconfigsys: {", ".join(bits)} — also on the TUI ! page; '
                      f'run `configsys check` for the full lint:')
                for d in sorted(diags, key=lambda d: 0 if d['level'] == 'error' else 1):
                    mark = '✗' if d['level'] == 'error' else '⚠'
                    print(f'  {mark} {d["tag"]:10} {d["text"]}')
            return
        ver = f' {self.os_info.version}' if self.os_info.version else ''
        r.event(report.VERBOSE, f'  session summary — {self.os_info.block}{ver}   '
                                f'install set: {_install_scope_label(cfg)}')
        tally = {}
        for st in states.values():
            tally[st.status] = tally.get(st.status, 0) + 1
        order = ('installed', 'outdated', 'missing', 'locked', 'unsupported', 'untrusted', 'error')
        parts = [f'{tally[s]} {s}' for s in order if tally.get(s)]
        r.event(report.VERBOSE, f'    {len(states)} unit(s): ' + ', '.join(parts))
        if diags:
            r.event(report.VERBOSE, f'    {len(diags)} issue(s):')
            for d in diags:
                mark = '✗' if d['level'] == 'error' else '⚠'
                r.event(report.VERBOSE, f'      {mark} {d["tag"]:10} {d["text"]}')


# -- commands -------------------------------------------------------------


# -- where: explain a component's routing ---------------------------------


# -- pin: view / set / promote install-method (and provider) pins ----------


# -- check: lint the merged config ----------------------------------------


# -- plugin: declare in `plugins:`, sync from git -------------------------


# NOTE: plugin add/remove/sync/bless/update orchestration moved to configsys.actions (F3 slice 4);
# cmd_plugin + the first-run offer call it.


# -- report: file an install-failure report (no hidden telemetry) ---------


# -- argument parsing -----------------------------------------------------


# Every verb lives in configsys/cli/ (review-2026-11-2 D2). What app.py itself calls is imported;
# every other moved name still resolves as `configsys.app.<name>` (plugins, scripts, tests)
# through the module __getattr__ below.
from .cli.ops import (  # noqa: E402
    cmd_inspect, _failure_diagnostics, cmd_fix_scope, cmd_install, cmd_remove, cmd_upgrade,
    cmd_updates, cmd_lock, cmd_unlock, cmd_set_version, cmd_uninstall, cmd_tui,
)
from .cli.common import _install_scope_label  # noqa: E402
from .cli.refresh import cmd_refresh  # noqa: E402
from .cli.where import (  # noqa: E402
    _layer_label, _source_label, cmd_search, cmd_where, cmd_location, cmd_versions,
)
from .cli.matrix import cmd_disp, cmd_picks, cmd_orphans, cmd_pin, cmd_machine, cmd_profile  # noqa: E402
from .cli.check import cmd_check, check_report  # noqa: E402
from .cli.plugin import _print_sync, cmd_plugin, _after_primary_commit  # noqa: E402
from .cli.issues import cmd_report, cmd_request, cmd_request_os  # noqa: E402
from .cli.settings import cmd_manpages, cmd_keys, cmd_show, cmd_config, cmd_theme  # noqa: E402
from .cli.parser import build_parser  # noqa: E402
from .cli.dotfiles import _dotfiles_diagnostics, cmd_dotfiles, cmd_glue  # noqa: E402

_MOVED = {  # name -> the configsys/cli module that defines it
    '_expand_profile_args_detail': 'ops',
    '_skip_unroutable_profile_members': 'ops', '_confirm_plan': 'ops', '_dispatch_op': 'ops',
    '_failure_open': 'ops', '_offer_report': 'ops',
    '_picks_selection': 'ops', '_merge_names': 'ops', '_ops_from_picks': 'ops',
    '_TIER_LABEL': 'ops', '_print_updates_groups': 'ops', '_print_update_notes': 'ops',
    'cmd_upgrade_system': 'ops', 'print_reboot_advisory': 'common',
    '_pretend_edit': 'common', '_warn_unknown_component': 'common',
    '_owned_index_sources': 'refresh', '_INDEX_SRC_DIRS': 'refresh',
    '_list_source_files': 'refresh', '_find_source_files': 'refresh',
    'diagnose_index_failure': 'refresh', '_source_key_fields': 'refresh',
    '_rekey_candidates': 'refresh', '_offer_rekey': 'refresh',
    '_orphaned_managed_sources': 'refresh', '_installed_owners': 'refresh',
    '_reconcile_managed_sources': 'refresh', '_NATIVE_REFRESH': 'refresh',
    '_FULL_UPGRADE_REFRESH': 'refresh', 'refresh_native_index': 'refresh',
    '_run_native_refresh': 'refresh', '_uses_native_index': 'refresh',
    'maybe_refresh_before_plan': 'refresh', '_upgradable_names': 'refresh',
    'published_pending': 'refresh', '_fmt_val': 'where', '_fmt_binding': 'where',
    '_os_version_conditions': 'where', 'where_report': 'where', 'where_profile_report': 'where',
    'active_snapshot': 'where', 'print_sync_delta': 'where', 'catalog_search': 'where',
    '_location_lines': 'where', 'write_location_cache': 'where',
    '_location_all': 'where', '_validate_pin': 'matrix',
    '_pin_list': 'matrix', '_pin_set': 'matrix', '_swap_headsup': 'matrix', '_pin_unset': 'matrix',
    '_pin_promote': 'matrix', '_issue_loc': 'check', '_fmt_conflict': 'plugin',
    '_git_init_commit': 'plugin', '_sweep_glue_to_primary': 'plugin',
    '_redeploy_user_glue': 'plugin', 'cmd_plugin_init': 'plugin',
    '_repoint_dotfile_links': 'plugin', '_plugin_init_create': 'plugin',
    '_plugin_init_merge': 'plugin', 'cmd_plugin_set_source': 'plugin', '_retarget_clone': 'plugin',
    'cmd_plugin_diff': 'plugin', '_primary_dir_name': 'plugin', '_CliPushUI': 'plugin',
    '_plugin_log': 'plugin', '_plugin_undo': 'plugin', '_edit_conflict': 'plugin',
    '_URL_PREFILL_LIMIT': 'issues', '_file_issue': 'issues', '_send_report': 'issues',
    '_MANPAGES': 'settings', '_manpage_targets': 'settings', '_SHOW_TARGETS': 'settings',
    '_show_file': 'settings', '_fmt_setting_value': 'settings', '_print_theme': 'settings',
    '_EPILOG': 'parser', '_version_string': 'parser', '_VersionAction': 'parser',
    '_GLUE_ORDER': 'dotfiles', '_default_glue_shell': 'dotfiles',
    '_open_in_editor': 'dotfiles', '_resolve_glue_unit': 'dotfiles',
    'cmd_glue_override': 'dotfiles', 'cmd_glue_add': 'dotfiles', 'cmd_dotfiles_staged': 'dotfiles',
    'cmd_dotfiles_activate': 'dotfiles', 'cmd_dotfiles_discard': 'dotfiles',
    '_print_user_glue': 'dotfiles',
    'cmd_dotfiles_status': 'dotfiles', 'cmd_dotfiles_capture': 'dotfiles',
}


def __getattr__(name):
    '''A name that moved to configsys/cli/ (PEP 562): `configsys.app.<name>` keeps working.'''
    mod = _MOVED.get(name)
    if mod is None:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    import importlib
    return getattr(importlib.import_module(f'.cli.{mod}', __package__), name)


# commands that never read the routes catalog: a forced --os is vetted against the os: sections alone
_CATALOG_FREE = frozenset({'show', 'keys', 'manpages'})


_COMMANDS = {
    'inspect': cmd_inspect,
    'dotfiles': cmd_dotfiles,
    'glue': cmd_glue,
    'uninstall': cmd_uninstall,
    'profile': cmd_profile,
    'config': cmd_config,
    'theme': cmd_theme,
    'install': cmd_install,
    'remove': cmd_remove,
    'upgrade': cmd_upgrade,
    'lock': cmd_lock,
    'unlock': cmd_unlock,
    'set-version': cmd_set_version,
    'fix-scope': cmd_fix_scope,
    'where': cmd_where,
    'search': cmd_search,
    'machine': cmd_machine,
    'orphans': cmd_orphans,
    'disp': cmd_disp,
    'picks': cmd_picks,
    'location': cmd_location,
    'versions': cmd_versions,
    'check': cmd_check,
    'pin': cmd_pin,
    'plugin': cmd_plugin,
    'updates': cmd_updates,
    'refresh': cmd_refresh,
    'report': cmd_report,
    'request': cmd_request,
    'request-os': cmd_request_os,
    'manpages': cmd_manpages,
    'show': cmd_show,
    'keys': cmd_keys,
    'tui': cmd_tui,
}


def _probe_color(ctx):
    '''`--probe`: print the resolved TUI color mode + motion (effects) and WHY, then exit — for
    debugging "why no color / no gradient". Briefly inits curses to read the terminal's caps.'''
    from .tui.theme import env_color_cap
    from .tui.menu import resolve_effects, is_ssh
    effects = resolve_effects(ctx)                    # also stamps CONFIGSYS_EFFECTS (fine — we exit)
    cap = env_color_cap()
    d = {}
    if sys.stdout.isatty():
        import curses
        from .tui.theme import Palette
        from .tui.screen import direct_color_env, direct_color_term
        d['term'] = direct_color_term()               # the -direct entry curses will start with

        def _p(_scr):
            pal = Palette(ctx.config.theme())
            d['mode'], d['colors'] = pal.color_mode, curses.COLORS
            try:
                d['can'] = curses.can_change_color()
            except curses.error:
                d['can'] = False
        try:
            with direct_color_env():
                curses.wrapper(_p)
        except Exception as e:                        # noqa: BLE001
            d['mode'] = f'(curses error: {e})'
    else:
        d['mode'] = '(not a terminal — capability probe skipped)'
    why = [x for x in (f"TERM={os.environ.get('TERM')}" + (f" (curses: {d['term']})" if d.get('term') else ''),
                       f"COLORTERM={os.environ.get('COLORTERM') or '(unset)'}",
                       f"COLORS={d['colors']}" if 'colors' in d else None,
                       f"can_change={d['can']}" if 'can' in d else None,
                       f'capped={cap}' if cap else None) if x]
    print(f"color:   {d.get('mode')}" + (f"   ({' · '.join(why)})" if why else ''))
    print(f"effects: {effects}   (SSH={'yes' if is_ssh(ctx.env) else 'no'})")
    return 0


# global options that take a value — skipped when a command line becomes a commit message
_GLOBAL_VALUE_OPTS = frozenset({'--os', '--home', '--machine', '--config', '--color', '--effects'})


def _command_words(argv, command):
    '''The command as typed, minus global flags — the commit message for a primary edit
    (`picks add btop`, `config set splash plain`). A `--machine NAME` is kept as a suffix.'''
    words = list(sys.argv[1:] if argv is None else argv)
    out, machine, i = [], None, 0
    while i < len(words):
        w = words[i]
        if w in _GLOBAL_VALUE_OPTS or any(w.startswith(o + '=') for o in _GLOBAL_VALUE_OPTS):
            val = w.split('=', 1)[1] if '=' in w else (words[i + 1] if i + 1 < len(words) else '')
            if w.startswith('--machine'):
                machine = val
            i += 1 if '=' in w else 2
            continue
        if not out and w.startswith('-'):
            i += 1
            continue
        out.append(w)
        i += 1
    msg = ' '.join(out) or command
    return msg + (f' (machine {machine})' if machine else '')


def main(argv=None):
    '''The CLI entry point. A downstream reader that closes the pipe early (`configsys … | head`)
    is normal, not an error: flush inside the guard so it surfaces here rather than in the
    interpreter's exit flush, point stdout at the void so that flush can't raise again, and exit
    like a SIGPIPE'd tool (app-cli-30).'''
    try:
        rc = _main(argv)
        sys.stdout.flush()
        return rc
    except BrokenPipeError:
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError, AttributeError):    # a captured / fd-less stdout (tests)
            pass
        return 141


def _main(argv):
    args = build_parser().parse_args(argv)
    # --nocolor / --color cap the TUI color depth via CONFIGSYS_COLOR (which the Palette + NO_COLOR
    # both read), set before anything builds a Palette. An explicit flag wins over the env.
    if getattr(args, 'nocolor', False):
        os.environ['CONFIGSYS_COLOR'] = 'none'
    elif getattr(args, 'color', None) and args.color != 'auto':
        os.environ['CONFIGSYS_COLOR'] = args.color
    if getattr(args, 'effects', None):                # --effects wins over the setting + SSH default
        os.environ['CONFIGSYS_EFFECTS'] = args.effects
    command = args.command or 'tui'
    try:
        ctx = Context(args)
    except ConfigsysError as e:                 # a malformed --os / CONFIGSYS_OS value
        print(f'configsys: {e}', file=sys.stderr)
        return 1
    if getattr(args, 'probe', False):
        return _probe_color(ctx)
    try:
        if ctx.os_info.forced and command != 'plugin':
            # a forced OS block must exist before any command runs on it — except the plugin
            # commands, which may be what brings that block (`plugin add`)
            ctx.check_os(light=command in _CATALOG_FREE)
        if command == 'tui':
            return _COMMANDS[command](ctx, args)       # the TUI commits per action (tui/menu.py)
        snap = primarygit.snapshot(ctx)                # commit what this command edits in the primary
        finished = False
        try:
            rc = _COMMANDS[command](ctx, args)
            finished = True
            return rc
        finally:
            # an interrupted / failed command is still committed (so its writes stay undoable), marked
            # as such — and NEVER pushed afterwards: you pressed Ctrl-C to stop (A13 / primary-07)
            words = _command_words(argv, command)
            for note in primarygit.commit(ctx, snap, words if finished else f'{words} (interrupted)'):
                print(f'configsys: {note}')
            if snap is not None and snap.committed:
                if finished:
                    _after_primary_commit(ctx)
                else:
                    print(f'configsys: what it wrote is committed to {snap.name} as interrupted, not '
                          'pushed — `configsys plugin undo` takes it back, `plugin push` shares it.')
    except ConfigsysError as e:
        print(f'configsys: {e}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:                 # any un-handled Ctrl-C exits cleanly, not a traceback
        try:
            ctx.runner.end_sudo()
        except Exception:                     # noqa: BLE001
            pass
        print('\nconfigsys: interrupted', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
