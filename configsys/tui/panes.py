'''panes.py — the models of the other screens — Profiles (ProfileScreen), Plugins, Glue, Dotfiles, Config
— and their cell helpers.

Split out of menu.py (review-2026-11-2 D2).
'''

import threading
from .. import primarygit
from ..errors import ConfigError
from ..drivers.glue import GLUE_STATE_LABEL as _GLUE_STATE_LABEL   # glue's active/available/inactive
from .modals import _attr_pass


# Serializes the ProfileScreen catalog warm-up (`_resolve` over ~800 components) against the UI
# thread's own `_resolve`. It is NOT required for every Resolver call: a resolve only READS the shared
# Resolver except for its memo caches (dict writes, atomic under the GIL), and only the load pipeline's
# `resolve_resilient(record=True)` writes the per-resolve state `where`/context() read (B16 /
# tui-core-06) — so the overlay / probe threads may resolve unlocked. One process-wide lock: there is
# one TUI per process, and keying it per ctx would miss two ctx wrappers over one routes.
_ROUTES_LOCK = threading.RLock()


def _routes_lock(ctx):
    '''The lock serializing TUI resolves through `ctx.routes` (see _ROUTES_LOCK).'''
    return _ROUTES_LOCK


class ProfileScreen:
    '''Two-panel profile editor: profiles (left) + the full component catalog (right). A skin over
    configsys.actions — space toggles membership, `a` toggles a profile active.'''
    def __init__(self, ctx):
        self.ctx = ctx
        self.focus = 'left'          # 'left' = profiles, 'right' = catalog
        self.lcur = self.rcur = self.ltop = self.rtop = 0
        self.rcol_left = 0           # matrix table horizontal CHAR offset (←/→ scroll; rhmax set at draw)
        self.lhoff = 0               # browse pane horizontal CHAR offset (for long names; lhmax at draw)
        self.rrows, self.rncols = 1, 1   # grid dims, set each draw; the key handler moves by column
        self.expanded_parts = set()      # catalog: `via: parts` comps drilled open -> parts as child rows
        self.pfilter = self.cfilter = ''   # substring filters for the profiles / catalog panes
        self.expanded = set()            # node keys of expanded profiles (inline `+include` tree)
        self.reveal = None               # key of a just-expanded node -> reveal its subtree next draw
        self.selected_comps = set()      # `space` multi-select: component names T/S/I act on as a batch
        self.target_machines = None      # v3 matrix: the selected edit-target machines (set); None -> {current}
        self._new_count_cache = {}       # profile -> (#NEW, #interesting) members; rebuilt lazily per reload
        self.attr_inc = set()            # `A` faceted attr filter: lowercased tags to INCLUDE
        self.attr_exc = {'dotfiles', 'glue'}   # ...and to EXCLUDE — hide the -dotfiles/-glue companions
                                               # by default (each has its own page)
        self._res = {}                   # component -> (available, via, pinned); survives reloads
        self._res_lock = threading.Lock()   # guards _res/_res_rid: _warm_cache fills it off-thread
        self._parts_cache = {}           # component -> its context-valid `via: parts` list; same lifecycle
                                         # as _res (a `when:`/pin thing, not a membership edit) — the
                                         # hot per-frame call, ~28ms/frame uncached on a 760-component catalog
        self._hard_dep_cache = {}        # component -> frozenset of its transitive hard component-requires
        self._avail_os_cache = {}        # component -> [platform labels where it routes] (lazy, for the infobox)
        self.show_install = 1 if ctx.config.install_overlay_default() else 0   # `O` toggles the install
        self._overlay = None             # overlay off/on (default from `install-overlay`, on unless set):
                                         # installed underlined, installed-but-unpicked ⊙ coloured
                                         # (dimmed when orphans-ignore lists it)
        self._scan_caches = None         # retained per-driver enumeration (installed/explicit/origin);
                                         # survives membership edits (reality is stable on this page) —
                                         # dropped only on an install/uninstall execute (invalidate_overlay)
        self._async_overlay = None       # (installed, orphans) delivered by the background orphan scan
        self._ov_gen = 0                 # generation guard: a stale async result (pre-reload) is dropped
        # per-component installed probe for NON-enumerable drivers (tarball/script/appImage/… — no
        # batch installed_index, so the overlay's `installed` set misses them). The draw queues the
        # visible catalog rows; a daemon thread checks get_version and folds results into the underline.
        self._probe_installed = {}       # name -> True (found installed on disk by an individual probe)
        self._probe_seen = set()         # names already queued/probed (never re-probe)
        self._probe_queue = []           # pending names for the probe thread
        self._probe_thread = None
        self._probe_dirty = False        # a new probe result arrived -> the menu loop repaints
        self.reload()

    def overlay(self):
        '''The install-axis overlay data when `show_install` is on: (installed set, {comp: Orphan},
        uninstall-queue set). ASYNC: the installed underlines paint IMMEDIATELY from the startup-seeded
        index (a pure dict map, no spawns), while the full scan — completing the installed set for
        non-seeded drivers PLUS the orphan classification (explicit_keys, ~1s) — runs on a daemon
        thread and folds in on a later redraw. So `O` never blocks the UI (the aim: leave it on by
        default). `invalidate_overlay()` drops the caches after an execute changes what's on disk.'''
        if not self.show_install:
            return (frozenset(), {}, frozenset())
        # fold a completed async result (for the CURRENT generation) into the shown overlay
        if self._async_overlay is not None:
            inst, orph = self._async_overlay
            self._async_overlay = None
            self._overlay = (inst, orph, set(self.ctx.config.uninstall_queue()))
        if self._overlay is None:
            from .. import orphans as _orph
            try:
                if self._scan_caches is None:
                    # seed the per-driver installed cache from the startup inspection's already-paid
                    # enumeration (a COPY). Post-reload (e.g. after an uninstall) it's refreshed.
                    seed = dict(getattr(self.ctx, 'startup_enum', None) or {})
                    self._scan_caches = {'inst': seed} if seed else {}
                installed = _orph.installed_overlay(self.ctx, self._scan_caches)   # instant (seed only)
                self._overlay = (installed, {}, set(self.ctx.config.uninstall_queue()))
                self._start_overlay_scan()                                         # orphans + full set async
            except Exception:            # noqa: BLE001 — the overlay must never brick the screen
                self._overlay = (frozenset(), {}, frozenset())
        return self._overlay

    def _start_overlay_scan(self):
        '''Run the full install_overlay (resolve + enumeration + orphan classification) on a daemon
        thread; deliver its result to `_async_overlay` iff no reload/invalidate has bumped the
        generation. The menu loop times out its getch while this is pending (overlay_busy) so the
        result paints on its own, without needing a keypress. resolve_resilient runs in the thread too
        — the fast paint needs only the seed + reverse index.'''
        from .. import orphans as _orph
        self._ov_gen += 1
        gen, caches = self._ov_gen, self._scan_caches

        def run():
            try:
                units, _e = self.ctx.routes.resolve_resilient(list(self.ctx.config.requested()))
                inst, orph, _c = _orph.install_overlay(self.ctx, units, caches=caches)
            except Exception:            # noqa: BLE001 — a scan failure just leaves the seed underlines
                return
            if self._ov_gen == gen:
                self._async_overlay = (inst, orph)
        self._ov_thread = threading.Thread(target=run, daemon=True)
        self._ov_thread.start()

    def overlay_busy(self):
        '''True while the background orphan scan is still running (its result not yet folded) — the
        menu loop uses this to poll for the async paint.'''
        return (self.show_install and self._async_overlay is None
                and getattr(self, '_ov_thread', None) is not None and self._ov_thread.is_alive())

    def invalidate_overlay(self):
        '''Drop BOTH the classification and the retained per-driver enumeration — call after an
        install/uninstall execute, when what's actually on disk may have changed.'''
        self._overlay = None
        self._scan_caches = None
        self._async_overlay = None
        self._ov_gen += 1                # abandon any in-flight scan's result
        self._probe_installed = {}       # on-disk reality changed -> re-probe the non-enumerable ones
        self._probe_seen = set()
        self._probe_queue = []

    def ensure_probes(self, names):
        '''Queue on-screen catalog rows NOT covered by the batch installed index for an individual
        installed check, so an installed browse component on a non-enumerable driver (tarball/script/
        appImage/source/cargo/…) still gets the underline. A name already in the overlay's `installed`
        set, or already probed, is skipped. Runs on a daemon thread; results fold into
        `_probe_installed` and the menu loop repaints (probe_busy).'''
        if not self.show_install:
            return
        ov = self._overlay[0] if self._overlay else frozenset()
        todo = [n for n in names if n not in ov and n not in self._probe_seen]
        if not todo:
            return
        self._probe_seen.update(todo)
        self._probe_queue.extend(todo)
        if self._probe_thread is None or not self._probe_thread.is_alive():
            self._start_probe()

    def _start_probe(self):
        # Check EVERY candidate binding of the component (like installState.detect_coexisting), not
        # just the resolved one — a tool is often installed via a NON-default method (e.g. ollama's
        # `script`/PATH install while `tarball` is the preference-picked default). Enumerable drivers
        # are skipped (the batch overlay set already covers them); non-enumerable ones use get_version.
        from ..driver import Driver
        from ..drivers import get_driver
        from ..adapt import to_resolved_component
        from ..resolve import candidate_bindings, unit_for_binding, via_representatives
        r = self.ctx.routes
        cx = r.context()

        def installed_any(name):
            comp = r.components.get(name)
            if comp is None or not comp.bindings:
                return False
            try:
                reps = via_representatives(candidate_bindings(comp, r.cascade, cx, None), r.cascade)
            except Exception:                        # noqa: BLE001
                return False
            for b in reps:
                unit = unit_for_binding(comp, b, r.cascade, r.block, r.overrides)
                if unit is None:
                    continue
                rc = to_resolved_component(unit)
                drv = get_driver(rc.driver, self.ctx.runner, self.ctx.paths)
                if drv is None or type(drv).installed_index is not Driver.installed_index:
                    continue                         # enumerable -> already in the batch set; skip
                try:
                    if drv.get_version(rc) is not None:
                        return True
                except Exception:                    # noqa: BLE001 — a flaky probe just leaves it un-underlined
                    pass
            return False

        def run():
            while self._probe_queue:
                name = self._probe_queue.pop()
                try:
                    if installed_any(name):
                        self._probe_installed[name] = True
                        self._probe_dirty = True
                except Exception:                    # noqa: BLE001
                    pass
        self._probe_thread = threading.Thread(target=run, daemon=True)
        self._probe_thread.start()

    def probe_busy(self):
        '''True while the per-component probe has pending work OR a fresh result to paint — the menu
        loop polls this (like overlay_busy) so underlines appear without a keypress.'''
        if self._probe_dirty:
            return True
        return bool(self._probe_queue) or (self._probe_thread is not None
                                           and self._probe_thread.is_alive())

    # -- profiles tree (top-level profiles + inline `+include` children) --

    def visible_pnodes(self):
        '''Flattened visible tree: [(name, depth, key, expandable, expanded, kind)]. `kind` is
        'profile' (a top-level profile) or 'include' (a `+other` child — a live include). A root
        profile's children are its `+includes`. `key` is the ancestor path (root =
        key.split('\\x00')[0] = the curated profile).'''
        # cache: the tree changes only with config identity (an edit -> ctx.invalidate) + the browse
        # toggles (filter / expand / collapse). Called ~5x per frame, so memoize on that.
        sig = (id(self.ctx.config), self.pfilter, frozenset(self.expanded))
        if getattr(self, '_vpn_sig', None) == sig:
            return self._vpn_cache
        f = self.pfilter.lower()
        # BROWSE LENS: every profile from any layer — the shipped catalog, plugins', and your own
        # (primary/top config: your browse categories, never an install set). Reserved names
        # (!uninstall, !all, @picks) are placed explicitly instead.
        browse = ([self.ctx.config.ALL_PROFILE]      # `!all` first: the browse-everything lens
                  + [p for p in self.profiles if not p.startswith(('!', '@'))]
                  + [self.ctx.config.UNINSTALL_PROFILE])   # `!uninstall`: the staged-removal queue, last
        roots = [p for p in browse if f in p.lower()] if f else browse
        out = []

        def walk(name, depth, path, kind):
            cfg = self.ctx.config
            key = '\x00'.join(path + [name])
            kids = [(c, 'include') for c in sorted(cfg.profile_includes(name))
                    if c not in path and c != name and c in self._profset]
            expandable = bool(kids)
            expanded = expandable and key in self.expanded
            out.append((name, depth, key, expandable, expanded, kind))
            if expanded:
                for c, ck in kids:
                    walk(c, depth + 1, path + [name], ck)

        for r in roots:
            walk(r, 0, [], 'profile')
        self._vpn_sig, self._vpn_cache = sig, out
        return out

    def node_kind(self, nd):
        return nd[5] if nd and len(nd) > 5 else 'profile'

    def cur_node(self):
        v = self.visible_pnodes()
        return v[self.lcur] if 0 <= self.lcur < len(v) else None

    def expand_cur(self):
        nd = self.cur_node()
        if nd and nd[3] and not nd[4]:               # expandable and collapsed
            self.expanded.add(nd[2])
            self.reveal = nd[2]                      # reveal the opened subtree on the next draw
            return True
        return False

    def collapse_cur(self):
        v = self.visible_pnodes()
        if not (0 <= self.lcur < len(v)):
            return
        nd = v[self.lcur]
        name, depth, key, expandable, expanded = nd[:5]
        if expanded:
            self.expanded.discard(key)
        elif depth > 0:                              # a child -> jump to its parent row
            for j in range(self.lcur - 1, -1, -1):
                if v[j][1] == depth - 1:
                    self.lcur = j
                    break

    def scoped_members(self):
        '''The catalog is ALWAYS scoped to the selected browse profile's members — the `!all` profile
        is the browse-everything lens, so no separate scope toggle.'''
        return self.members(self.cur_curate())

    def _profile_counts(self, name):
        '''(#NEW, #interesting) among `name`'s members, in one pass. NEW = undispositioned &
        untriaged (is_new); interesting = bookmarked (disposition). Memoized.'''
        key = name
        cache = self._new_count_cache
        if key not in cache:
            cfg = self.ctx.config
            try:
                mem = self.members(name)
                nnew = sum(1 for c in mem if cfg.is_new(c) and not self._is_companion(c))
                nint = sum(1 for c in mem if cfg.disposition(c) == 'interesting')
                cache[key] = (nnew, nint)
            except Exception:                            # noqa: BLE001 — a bad profile counts nothing
                cache[key] = (0, 0)
        return cache[key]

    def profile_new_count(self, name):
        '''#NEW members of `name` (the `⁺N` badge). Memoized until the next reload.'''
        return self._profile_counts(name)[0]

    def profile_interesting_count(self, name):
        '''#INTERESTING (bookmarked) members of `name` (the `☆N` badge). Memoized until reload.'''
        return self._profile_counts(name)[1]

    def profile_untracked_count(self, name):
        '''#members of `name` that are INSTALLED on this box but NOT tracked on the current machine
        (the `⊙N` badge — claimable). Memoized per (config, profile, probe results seen): a frame
        asked it for every visible row (~half the screen's per-keystroke cost — C6).'''
        key = (id(self.ctx.config), name, id(getattr(self, '_overlay', None)),
               len(getattr(self, '_probe_installed', None) or {}), getattr(self, 'show_install', None))
        memo = self.__dict__.setdefault('_untracked_memo', {})
        if key in memo:
            return memo[key]
        if len(memo) > 512:
            memo.clear()
        memo[key] = n = self._profile_untracked_count(name)
        return n

    def _profile_untracked_count(self, name):
        tracked = self.ctx.config.included()
        try:
            mem = self.members(name)
        except Exception:                            # noqa: BLE001
            return 0
        return sum(1 for c in mem if c not in tracked and self.install_state(c, force=True) != 'none')

    def _parts(self, name):
        '''The parts of `name`'s CONTEXT-VALID `via: parts` binding — component-level `parts:` plus the
        parts of the binding(s) whose `when:` applies on THIS machine. Empty for an ordinary component.
        Filtering by `when:` is essential: a component like vulkan-runtime lists DIFFERENT parts per OS,
        so unioning across all bindings would count another distro's packages as missing parts and
        falsely read the aggregate as partially installed (◐).'''
        cached = self._parts_cache.get(name)
        if cached is not None:
            return cached
        comp = self.ctx.routes.components.get(name)
        if comp is None:
            self._parts_cache[name] = []
            return []
        out = list(getattr(comp, 'parts', []) or [])
        r = self.ctx.routes
        try:
            from ..resolve import candidate_bindings
            cx = r.context()
            binds = candidate_bindings(comp, r.cascade, cx, self.ctx.config.pins())
        except Exception:                            # noqa: BLE001 — fall back to all bindings
            binds = comp.bindings
        for b in binds:
            p = b.details.get('parts')
            if isinstance(p, str):
                out.append(p)
            elif isinstance(p, (list, tuple)):
                out.extend(str(x) for x in p)
        seen, uniq = set(), []
        for p in out:
            if p not in seen:
                seen.add(p)
                uniq.append(p)
        self._parts_cache[name] = uniq
        return uniq

    def _hard_deps(self, name, _stack=()):
        '''`name`'s transitive HARD requires that are themselves COMPONENTS — the deliberate
        component-to-component dependencies (the `virt-manager -> libvirt-service` service-companion
        shape). Deliberately EXCLUDES capability requires (fuzzy — satisfied by any provider) and
        `suggests:` soft-deps (the -dotfiles/-select/-glue companions), so this never flags the
        incidental "optional companion not materialized" partial. Cached per reload.'''
        if name in self._hard_dep_cache:
            return self._hard_dep_cache[name]
        comps = self.ctx.routes.components
        comp = comps.get(name)
        out = set()
        if comp is not None and name not in _stack:
            for dep in (getattr(comp, 'requires', None) or []):
                if isinstance(dep, str) and dep in comps and dep not in _stack:
                    out.add(dep)
                    out |= self._hard_deps(dep, _stack + (name,))
        self._hard_dep_cache[name] = frozenset(out)
        return self._hard_dep_cache[name]

    def install_state(self, name, _stack=(), force=False):
        '''Tri-state install status for the `inst'd` column: 'all' (fully on disk), 'some' (partial),
        or 'none'. Partial (◐) means either a `via: parts` aggregator with only SOME parts installed,
        OR an installed component whose hard component-requires aren't all present (e.g. an app
        installed without its required service). `force` ignores the `O` display toggle (for the C
        claim, which reads reality regardless).'''
        if (not self.show_install and not force) or name in _stack:
            return 'none'
        parts = self._parts(name)
        if parts:
            sub = [self.install_state(p, _stack + (name,), force=True) for p in parts]
            if sub and all(s == 'all' for s in sub):
                return 'all'
            return 'some' if any(s != 'none' for s in sub) else 'none'
        ov = self._overlay[0] if self._overlay else frozenset()
        if not (name in ov or bool(self._probe_installed.get(name))):
            return 'none'
        # installed — but is its hard component-requires closure fully present too?
        deps = self._hard_deps(name)
        if any(d not in ov and not self._probe_installed.get(d) for d in deps):
            return 'some'
        return 'all'

    def is_installed(self, name, force=False):
        '''True iff `name` is FULLY installed (a parts aggregator: all parts). For the name underline
        and the C claim.'''
        return self.install_state(name, force=force) == 'all'

    def installed_scan(self):
        '''Full-catalog installed detection for `C` (claim): the enumerable-driver batch set
        (catalog-wide) PLUS a per-component get_version across every NON-enumerable candidate binding
        (so tarball/script/appImage installs are caught, not just the on-screen probed ones) PLUS
        parts aggregators whose parts are all present. Synchronous — the caller flashes a busy note.'''
        from .. import orphans as _orph
        from ..driver import Driver
        from ..drivers import get_driver
        from ..adapt import to_resolved_component
        from ..resolve import candidate_bindings, unit_for_binding, via_representatives
        ctx, r = self.ctx, self.ctx.routes
        cx = r.context()
        try:
            units, _e = r.resolve_resilient(list(ctx.config.requested()))
            inst, _o, _c = _orph.install_overlay(ctx, units, caches=self._scan_caches)
        except Exception:                            # noqa: BLE001
            inst = self._overlay[0] if self._overlay else frozenset()
        hits = set(inst)

        def leaf_installed(name):
            comp = r.components.get(name)
            if comp is None or not comp.bindings:
                return False
            try:
                reps = via_representatives(candidate_bindings(comp, r.cascade, cx, None), r.cascade)
            except Exception:                        # noqa: BLE001
                return False
            for b in reps:
                unit = unit_for_binding(comp, b, r.cascade, r.block, r.overrides)
                if unit is None:
                    continue
                rc = to_resolved_component(unit)
                drv = get_driver(rc.driver, ctx.runner, ctx.paths)
                if drv is None or type(drv).installed_index is not Driver.installed_index:
                    continue                         # enumerable driver -> already covered by `inst`
                try:
                    if drv.get_version(rc) is not None:
                        return True
                except Exception:                    # noqa: BLE001
                    pass
            return False

        cat = list(self.catalog)
        for c in cat:
            if c not in hits and not self._parts(c) and leaf_installed(c):
                hits.add(c)
        for c in cat:                                # a parts aggregator installed iff all its parts are
            p = self._parts(c)
            if p and all(x in hits for x in p):
                hits.add(c)
        return sorted(hits & set(cat))

    def origin(self, name):
        '''Where a component is DEFINED — 'repo' · a plugin's name · 'local' — for the catalog's
        origin column (so repo + plugins read as one consolidated browse list).'''
        comp = self.ctx.routes.components.get(name)
        src = str(getattr(comp, 'source', '') or '')
        if not src:
            return 'repo'
        paths = self.ctx.paths
        if src in (str(paths.routes_file), str(getattr(paths, 'config_file', ''))):
            return 'repo'
        if src == str(paths.user_config_file):
            return 'local'
        pdir = str(paths.plugins_dir)
        if src.startswith(pdir):
            return (src[len(pdir):].lstrip('/').split('/') or ['plugin'])[0] or 'plugin'
        return 'repo'

    # -- v3 matrix: machines (columns) + Included (picks) state --
    def machines_list(self):
        '''Every machine to show a column for: the defined `machines:` names, else just the current
        machine (a one-machine user never has to name it). Sorted, current machine first.'''
        ms = self.ctx.config.machine_names()
        cur = self.ctx.config.current_machine()
        if cur not in ms:
            ms = [cur] + ms
        else:
            ms = [cur] + [m for m in ms if m != cur]
        return ms

    def targets(self):
        '''The edit-target machines T/t/enter fan out to. `target_machines` is None by DEFAULT (the
        modal was never opened) -> this box's current machine; once you edit the target set it's used
        verbatim — so you CAN target only OTHER machines (edit their picks from here), or none at all
        (then tracking simply no-ops).'''
        tm = self.target_machines
        return set(tm) if tm is not None else {self.ctx.config.current_machine()}

    def target_state(self, comp):
        '''Whether `comp` is picked across the TARGET machines: "all" · "some" · "none" — the
        actionable Included summary (what A/D toggles).'''
        picks = self.ctx.config.picks()
        tg = self.targets()
        if not tg:                                   # no targets selected -> nothing to be tracked on
            return 'none'
        hits = sum(1 for m in tg if comp in picks.get(m, ()))
        return 'all' if hits == len(tg) else ('some' if hits else 'none')

    def cursor_targets(self):
        '''The HIGHLIGHTED item's components (ignoring the multi-select set): the catalog cursor when
        the right pane is focused, else ALL members of the selected browse profile (the left pane's
        highlighted item). Drives `t`/`s`/`i`.'''
        if self.focus == 'left':
            prof = self.cur_curate()
            return sorted(self.members(prof)) if prof else []
        vc = self.vcatalog()
        return [vc[self.rcur]] if vc and 0 <= self.rcur < len(vc) else []

    def action_targets(self):
        '''The batch a `T` action applies to: the `space` multi-select set (explicit, spans profiles)
        if any, else the highlighted item (cursor_targets). Does NOT clear the set.'''
        return sorted(self.selected_comps) if self.selected_comps else self.cursor_targets()

    def _base_catalog(self):
        '''The filtered TOP-LEVEL catalog names (cfilter + scoped-profile membership + attr filter),
        before any expanded `via: parts` children are interleaved.'''
        f = self.cfilter.lower()
        cat = [c for c in self.catalog if f in c.lower()] if f else self.catalog
        sm = self.scoped_members()                   # always the selected browse profile's members
        cat = [c for c in cat if c in sm]
        if self.attr_inc or self.attr_exc:           # `A` attrs filter (faceted include/exclude)
            comps = self.ctx.routes.components
            cat = [c for c in cat if _attr_pass(
                {a.lower() for a in getattr(comps.get(c), 'attrs', [])}, self.attr_inc, self.attr_exc)]
        return cat

    def is_expandable(self, name):
        '''True if `name` is a `via: parts` aggregator (has drill-in pieces on this machine).'''
        return bool(self._parts(name))

    def toggle_expand_part(self, name):
        if name in self.expanded_parts:
            self.expanded_parts.discard(name)
        elif self.is_expandable(name):
            self.expanded_parts.add(name)

    def _catalog_rows(self):
        '''The catalog as `[(name, depth)]`: each top-level component at depth 0, and — for an
        EXPANDED `via: parts` aggregator — its context-valid parts as depth-1 child rows right below.
        A part is an ordinary component, so its child row tracks / pins / reads state by name.'''
        rows = []
        for name in self._base_catalog():
            rows.append((name, 0))
            if name in self.expanded_parts:
                for p in self._parts(name):
                    rows.append((p, 1))
        return rows

    def vcatalog(self):
        return [name for name, _depth in self._catalog_rows()]

    def attr_summary(self):
        '''Short `✓a ✗b` chip for the catalog title, or '' at the pristine default (only the
        implicit `-dotfiles`/`-glue` companion hide, which the nav hint already advertises).'''
        parts = ['✓' + t for t in sorted(self.attr_inc)] + ['✗' + t for t in sorted(self.attr_exc)]
        if parts == ['✗dotfiles', '✗glue']:
            return ''
        return '  ' + ' '.join(parts) if parts else ''

    def _is_companion(self, comp):
        '''True if `comp` is a -dotfiles / -glue companion — it lives on the Dotfiles/Glue page, not
        the Components catalog, so it's excluded from the catalog's NEW/interesting badges.'''
        o = self.ctx.routes.components.get(comp)
        if o is None:
            return False
        return bool({a.lower() for a in getattr(o, 'attrs', [])} & {'dotfiles', 'glue'})

    def set_pfilter(self, text):
        self.pfilter = text
        self.lcur = max(0, min(self.lcur, len(self.visible_pnodes()) - 1))

    def set_cfilter(self, text):
        self.cfilter = text
        self.rcur = max(0, min(self.rcur, len(self.vcatalog()) - 1))
        self.rcol_left = 0

    def reload(self):
        cfg = self.ctx.config
        self._overlay = None                         # recompute the overlay CLASSIFICATION after an edit
                                                     # (keeps _scan_caches — reality is unchanged here)
        self._async_overlay = None                   # abandon any in-flight scan; the recompute restarts it
        self._ov_gen = getattr(self, '_ov_gen', 0) + 1
        self.profiles = cfg.profile_names()
        self._profset = set(self.profiles)
        self._new_count_cache = {}                    # NEW badges recompute after any edit
        self.selected_comps &= set(self.ctx.routes.components)   # drop selections for gone components
        self.catalog = sorted(self.ctx.routes.components)
        # KEEP self._res: a membership / profile edit doesn't change how a component RESOLVES (its
        # via), so re-resolving the whole visible set (~17ms each) on every toggle was the ~1.5s lag.
        # The method picker (`m`) is the only edit that changes resolution; it drops its own entry.
        self.lcur = max(0, min(self.lcur, len(self.visible_pnodes()) - 1))
        self.rcur = max(0, min(self.rcur, len(self.vcatalog()) - 1))
        self._warm_cache()               # resolving each component is ~17ms; warm off-thread so
                                         # scrolling the catalog isn't sluggish the first time through

    def _warm_cache(self):
        '''Populate _resolve for the whole catalog on a daemon thread. The menu loop blocks in
        getch() (GIL released) while idle, so this fills within a few seconds of opening the screen
        without stuttering the UI. A generation guard makes a later reload() abandon this sweep.'''
        if (getattr(self, '_res_rid', None) == id(self.ctx.routes)
                and all(nm in self._res for nm in self.catalog)):
            return                                   # already warm FOR THESE routes (survives reloads)
        self._warm_gen = getattr(self, '_warm_gen', 0) + 1
        gen, catalog = self._warm_gen, list(self.catalog)

        def run():
            for name in catalog:
                if self._warm_gen != gen:            # a reload superseded us — stop
                    return
                try:
                    self._resolve(name)
                except Exception:                    # noqa: BLE001 — never let warming crash
                    pass
        threading.Thread(target=run, daemon=True).start()

    def cur_profile(self):
        nd = self.cur_node()
        return None if nd is None else nd[0]

    def cur_curate(self):
        '''The profile the RIGHT catalog edits reflect: the current node's own profile.'''
        nd = self.cur_node()
        if nd is None:
            return None
        return nd[0]

    def members(self, profile):
        try:
            return set(self.ctx.config.profile_components(profile)) if profile else set()
        except ConfigError:
            return set()

    def relation(self, profile):
        '''Provenance of the profile's top definition vs any lower same-name def: 'tracked' (`+self`),
        'shadowed', or 'base' — drives the pane's provenance badge glyph.'''
        try:
            return self.ctx.config.profile_relation(profile) if profile else 'base'
        except Exception:                                # noqa: BLE001
            return 'base'

    def _resolve(self, name):
        '''(available, resolved_via, pinned) for a component — cached. The resolved via is the
        method it installs with now (the pin, else the preference-picked default); `pinned` is set
        when a binding-pin chose it. One candidates() call feeds both the grey-out and the method.'''
        # Drop the cache when ctx.routes was rebuilt (a pin / route / plugin edit calls ctx.invalidate,
        # which swaps in a fresh Resolver) — even one made from ANOTHER screen. A membership/profile
        # edit does NOT invalidate, so its `id` is unchanged and the cache survives (the perf win).
        #
        # Thread-safe: the `_warm_cache` daemon thread calls this concurrently with the UI thread. The
        # cache check/clear/insert runs under `_res_lock`; the (slow) resolve runs outside it, under
        # the per-ctx `_routes_lock` so no two threads drive one Resolver's internal caches at once
        # (also across two ProfileScreens over one ctx). The insert is a setdefault — a value already
        # present (another thread's, or a deliberate priming) wins — and is skipped if ctx.routes was
        # swapped mid-resolve (that result belongs to the old routes).
        routes = self.ctx.routes
        rid = id(routes)
        with self._res_lock:
            if rid != getattr(self, '_res_rid', None):
                self._res.clear()
                self._res_rid = rid
            hit = self._res.get(name)
        if hit is not None:
            return hit
        with _routes_lock(self.ctx):
            try:
                cands = routes.candidates(name)
            except Exception:                       # noqa: BLE001 — unroutable
                cands = []
        win = next((c for c in cands if c['default']), None)
        val = (bool(cands), win['via'] if win else None, bool(win and win['pinned']))
        with self._res_lock:
            if getattr(self, '_res_rid', None) != rid:
                return val                           # routes rebuilt meanwhile: don't cache a stale value
            return self._res.setdefault(name, val)

    def available(self, name):
        return self._resolve(name)[0]

    def available_oses(self, name):
        '''Representative OS-family labels where `name` DOES resolve (the coverage matrix) — for the
        infobox hint on a component with no install method on THIS box. Lazy + cached (7 resolves).'''
        if name not in self._avail_os_cache:
            try:
                from .. import reportgen
                self._avail_os_cache[name] = [r['label'] for r in reportgen.coverage(self.ctx, name)
                                              if r.get('ok')]
            except Exception:                        # noqa: BLE001 — never let it break the detail box
                self._avail_os_cache[name] = []
        return self._avail_os_cache[name]

    def method(self, name):
        '''(resolved_via, pinned) for the row's method label.'''
        _avail, via, pinned = self._resolve(name)
        return via, pinned


# Short two/three-letter tags for the cross-cutting install methods in `driver-preference`, so the
# whole ordered list fits the Config value column. The reorder modal spells each one out (`na: native`).
_DRIVER_ABBR = {'native': 'na', 'aur': 'au', 'flatpak': 'fp', 'snap': 'sn', 'native-pkg-file': 'nf',
                'appImage': 'ai', 'brew': 'br', 'tarball': 'tb', 'source': 'src', 'script': 'sc'}


def _setting_str(kind, val, key=None):
    if key == 'scope' and val in (None, ''):
        return 'user (default)'
    if kind == 'map' and isinstance(val, dict):               # (defensive: a raw mapping -> tokens)
        val = [f'{k}={v}' for k, v in sorted(val.items())]
    if kind in ('list', 'map'):                               # map = `key=value` tokens, shown like a list
        if not val:
            return '(unset — built-in default)'
        if key == 'driver-preference':                        # abbreviate so the order fits the column
            return ' '.join(_DRIVER_ABBR.get(d, d) for d in val)
        return ' '.join(val)
    if kind == 'bool':
        return 'true' if val else 'false'
    return str(val) if val not in (None, '') else '(unset)'


# -- Config screen --------------------------------------------------------
class ConfigScreen:
    '''Machine-settings form — a skin over configsys.actions.config_settings/set_config_setting.'''
    def __init__(self, ctx):
        self.ctx = ctx
        self.cur = 0
        self.top = 0                      # first visible setting (variable-height blocks -> scroll)
        self.reload()

    def reload(self):
        from .. import actions
        self.settings = actions.config_settings(self.ctx)
        self.keys = list(self.settings)
        self.cur = max(0, min(self.cur, len(self.keys) - 1))
        self.top = min(self.top, self.cur)


# -- Plugins screen -------------------------------------------------------
# Column headers; widths are computed per-draw to fit content (name/source show full length).
_PLUGIN_HEADERS = ['name', 'source', 'ref', 'remote-ref', 'abi', 'code', 'provides']


_DIFF_ELEM = {'add': 'diff_add', 'del': 'diff_del', 'hunk': 'diff_hunk',
              'meta': 'diff_meta', 'ctx': 'info_dim'}


class PluginScreen:
    '''Two-pane Plugins screen. TOP: a `tree`-style table of declared plugins (incl. transitive)
    with name│source│ref│remote-ref│abi│code│provides columns — j/k select, h/l scroll columns.
    BOTTOM: the review diff for the selected plugin (actions.plugin_review_plan): a synced plugin's
    on-disk copy -> its remote-ref, or, unsynced, its ref -> remote-ref (or the whole content a sync
    would download) fetched into an inert review cache. Loaded on a background thread as the cursor
    settles, cached per (plugin, base, target); files as headers; hjkl scroll. Tab cycles focus
    table→diff→next file→table; Shift-Tab reverses. A skin over configsys.actions.plugin_* —
    add/remove/sync/bless/update/trust/lock.'''

    def __init__(self, ctx, *, load=True):
        self.ctx = ctx
        self.cur = 0
        self.top = 0
        self.hscroll = 0                 # horizontal scroll across the columns
        self.focus = 'table'             # 'table' | 'diff'
        self.remote = {}                 # dir_name -> ref(str) | 'pending' | None(unreachable/none)
        self._remote_gen = 0
        self.dfile = 0                   # selected file within the loaded diff
        self.dtop = 0                    # vertical scroll within the diff file
        self.dhscroll = 0                # horizontal scroll within the diff
        self.diff_key = None             # (name, kind, base, target) the shown diff belongs to
        self.diff_files = []
        self.diff_note = ''
        self.diff_span = None            # (from, to, what) for the diff pane title
        self._diff_cache = {}            # diff_key -> (files, note)
        self._diff_want = None           # (diff_key, thunk) the worker should run next
        self._diff_busy = False
        self._diff_awaiting = None       # the diff_key queued but not yet shown
        self._diff_lock = threading.Lock()
        if load:                         # (a Theme preview sample fills its own rows: no real load)
            self.reload()

    def reload(self):
        from .. import plugins
        self.tree = plugins.declared_tree(self.ctx.paths.user_config_file, self.ctx.paths.plugins_dir)
        self.rows = plugins.status(self.ctx.paths.plugins_dir, [t['decl'] for t in self.tree],
                                   trust_file=self.ctx.paths.plugin_trust_file,
                                   lock_file=self.ctx.paths.plugin_lock_file)
        self.cur = max(0, min(self.cur, len(self.rows) - 1))
        self._set_primary_state(primarygit.state(self.ctx))   # local counts now; the fetch refines them
        self._diff_cache = {}            # a sync/update may have moved what's on disk
        self._invalidate_diff()
        self._start_remote()

    def cur_row(self):
        return self.rows[self.cur] if 0 <= self.cur < len(self.rows) else None

    def cur_tree(self):
        return self.tree[self.cur] if 0 <= self.cur < len(self.tree) else None

    def _set_primary_state(self, st):
        '''Where the primary stands (primarygit.state) — shown on its row, and mirrored on the ctx for
        the Components header chip.'''
        self.primary_state = st
        self.ctx._primary_state = st

    def _start_remote(self):
        '''Resolve each plugin's remote-ref on a daemon thread (read-only `git ls-remote`); the
        table shows '…' until each lands. Like ProfileScreen._warm_cache: the menu loop blocks in
        getch() while idle, so cells fill without stalling screen entry on the network.'''
        from .. import plugins
        self._remote_gen += 1
        gen, rows = self._remote_gen, list(self.rows)
        for r in rows:
            self.remote.setdefault(plugins.dir_name(r['source']), 'pending')

        def run():
            if any(r.get('primary') for r in rows):      # fetch the primary first: ↓N needs the remote
                try:
                    if primarygit.fetch(self.ctx) and self._remote_gen == gen:
                        self._set_primary_state(primarygit.state(self.ctx))
                except Exception:                        # noqa: BLE001 — never let it crash
                    pass
            for r in rows:
                if self._remote_gen != gen:              # a reload superseded us
                    return
                key = plugins.dir_name(r['source'])
                try:
                    ref, _kind = plugins.latest_ref(self.ctx.runner, r['source'])
                    self.remote[key] = ref               # str, or None if unreachable / no ref
                except Exception:                        # noqa: BLE001 — never let it crash
                    self.remote[key] = None
        threading.Thread(target=run, daemon=True).start()

    def _invalidate_diff(self):
        self.diff_key, self.diff_files, self.diff_note, self.diff_span = None, [], '', None
        self._diff_awaiting = None
        self.dfile = self.dtop = self.dhscroll = 0

    def busy(self):
        '''True while a remote-ref or review diff is still being fetched — the menu loop polls so
        the result paints without a keypress.'''
        return (self._diff_busy or self._diff_awaiting is not None
                or any(v == 'pending' for v in list(self.remote.values())))

    def load_diff(self):
        '''Show the selected plugin's review diff (actions.plugin_review_plan): from the cache when
        it's been fetched, else queue it on the background worker and say so. Cheap and idempotent —
        the screen calls it after every key and on each poll tick.'''
        from .. import actions, plugins
        row, node = self.cur_row(), self.cur_tree()
        if row is None or node is None:
            self._invalidate_diff()
            self.diff_note = 'no plugin selected'
            return
        key = plugins.dir_name(row['source'])
        remote = self.remote.get(key)
        if remote == 'pending':
            self.diff_key, self.diff_files, self.diff_span = None, [], None
            self.diff_note = 'resolving remote-ref…'
            return
        plan = actions.plugin_review_plan(row, remote if isinstance(remote, str) else None)
        kind, base, target, what = plan
        ident = (key, kind, base, target)
        if ident == self.diff_key:
            return
        frm = ('∅' if base is None else (row['ref'] or 'HEAD') if base == 'HEAD' else base)
        span = (frm, target, what) if kind else None
        if kind is None:
            self._show(ident, [], what, span)
        elif ident in self._diff_cache:
            self._show(ident, *self._diff_cache[ident], span)
        elif getattr(self.ctx.runner, 'pretend', False):
            self._show(ident, [], '--pretend: the review diff fetches nothing', span)
        else:
            self.diff_key, self.diff_files, self.diff_span = None, [], span
            self.diff_note = f'fetching {target} to review…'
            self._diff_awaiting = ident
            decl, rref = node['decl'], remote if isinstance(remote, str) else None
            self._request_diff(ident, lambda: actions.plugin_review(self.ctx, decl, row, rref)[:2])

    def _show(self, ident, files, note, span):
        self._diff_awaiting = None
        if ident != self.diff_key:
            self.dfile = self.dtop = self.dhscroll = 0
        self.diff_key, self.diff_files, self.diff_note, self.diff_span = ident, files, note, span
        self.dfile = max(0, min(self.dfile, len(files) - 1))

    def _request_diff(self, ident, thunk):
        '''Run `thunk` for `ident` on the single worker thread. Only the NEWEST request matters: a
        cursor scrolling past rows never fetches the ones it passed over.'''
        with self._diff_lock:
            self._diff_want = (ident, thunk)
            if self._diff_busy:
                return
            self._diff_busy = True

        def run():
            while True:
                with self._diff_lock:
                    job, self._diff_want = self._diff_want, None
                    if job is None:
                        self._diff_busy = False
                        return
                ident_, thunk_ = job
                if ident_ in self._diff_cache:
                    continue
                try:
                    files, note = thunk_()
                except Exception as e:               # noqa: BLE001 — never let it crash
                    files, note = [], f'review failed: {e}'
                self._diff_cache[ident_] = (files, note)
        threading.Thread(target=run, daemon=True).start()


def _plugin_tree_prefix(node):
    '''The ├─ │ └─ prefix for a tree row from its ancestry is-last flags. Roots sit flush-left, and
    a depth-1 child's connector starts at column 0 (under the root name's first letter) — the root
    level contributes no indent (flags[1:-1]), so the tree stays tight against the name column.'''
    flags = node['last']
    if node['depth'] == 0:
        return ''
    return ''.join('   ' if f else '│  ' for f in flags[1:-1]) + ('└─ ' if flags[-1] else '├─ ')


def _plugin_provides_cell(row):
    '''Every provision as its short code (plugins.PROVISIONS; spelled out on the `?` page) — what
    the plugin actually ships, falling back to its manifest `provides:` keys when it isn't synced.'''
    from .. import plugins
    keys = row.get('provisions') or (list(row['provides']) if isinstance(row.get('provides'), dict)
                                     else [])
    return ' '.join(plugins.PROVISION_CODES.get(plugins._PROVIDES_ALIASES.get(k, k), k)
                    for k in keys) or '—'


def _plugin_cells(row, node, remote, pstate=None):
    '''The seven column strings for a plugin row (name carries the tree prefix, ⊘ locked, ★). The
    primary's remote-ref also carries where it stands (`pstate`, primarygit.glyphs): ↑N ↓N ●.'''
    rref = '…' if remote == 'pending' else (remote if isinstance(remote, str) else '—')
    marks = primarygit.glyphs(pstate) if row.get('primary') else ''
    if marks:
        rref = f'{rref} {marks}'
    mark = ('⊘' if row.get('locked') else '') + ('★' if row['primary'] else '')
    return [f'{_plugin_tree_prefix(node)}{mark}{row["name"]}',
            row['source'], row['ref'] or '—', rref,
            'ok' if row['abi_ok'] else f'≠{row["requires_abi"]}',
            # the trust column: a code: module OR command-carrying recipes both need trust (code_state
            # already reflects either); '—' only when there is nothing to trust.
            row['code_state'] if (row['has_code'] or row.get('has_recipes')) else '—',
            _plugin_provides_cell(row)]


def _plugin_remote_elem(row, remote, pstate=None):
    if row.get('primary') and primarygit.glyphs(pstate):
        return 'outdated'                                # something to push, sync or commit
    if remote == 'pending' or not isinstance(remote, str) or row.get('locked'):
        return 'info_dim'                                # a locked plugin's update can't be taken
    return 'installed' if remote == (row['ref'] or None) else 'outdated'   # green=up-to-date, amber=update


def _plugin_code_elem(row):
    return {'trusted': 'installed', 'untrusted': 'untrusted', 'changed': 'untrusted',
            'none': 'info_dim', 'unsynced': 'info_dim'}.get(row['code_state'], 'info_dim')


# -- Dotfiles screen ------------------------------------------------------
# state -> theme element. `managed` (a .cfs marker exists but nothing is captured yet — capture to
# link) and `unmanaged` (a real file we don't manage — at risk) both want attention; `loader-on/off`
# are the per-shell glue loaders (zsh-glue/fish-glue).
_DF_STATE_ELEM = {  # config DISPLAY states (managed/unmanaged/no config) + glue RAW states
    'managed': 'installed', 'unmanaged': 'outdated', 'no config': 'info_dim',
    'linked': 'installed', 'loader-on': 'installed', 'template': 'info_dim', 'loader-off': 'info_dim',
    'drifted': 'outdated',                              # active but the shipped snippet changed -> re-activate
    'unlinked': 'info_dim'}                             # a user glue snippet not linked into conf.d


_DF_CAPTURE_STATES = ('managed', 'unmanaged')          # rows a capture would adopt


class _ContentRootLabelMixin:
    def _root_label(self, root):
        '''Short label for a content root: <plugin> / <local> / <repo> / <plugin-name> — so SOURCE
        says WHERE the content lives (shared with the CLI: Paths.content_root_label).'''
        return self.ctx.paths.content_root_label(root)


class DotfilesScreen(_ContentRootLabelMixin):
    '''Link-state table over the via:dotfiles (CONFIG) units — a skin over the dotfiles driver
    (spec_states / install / uninstall / capture). Glue lives on its own page (GlueScreen).'''
    def __init__(self, ctx, *, load=True):
        self.ctx = ctx
        self.cur = 0
        self.top = 0
        self.hscroll = 0                 # horizontal scroll across the columns (h/l)
        self.dirty = set()               # unit keys mutated here -> requeried on return to Components
        if load:                         # (a Theme preview sample fills its own rows: no real load)
            self.reload()

    def reload(self):
        from .. import actions
        from ..drivers import get_driver
        _df, units = actions.dotfiles_units(self.ctx)
        self.units = [rc for rc in units if rc.driver == 'dotfiles']
        self.df = get_driver('dotfiles', self.ctx.runner, self.ctx.paths)
        cfg = []                                             # (rc, name, tgt, state, source, cap)
        for rc in self.units:
            # a `managed`/`unmanaged` row is capture-ACTIONABLE only when a real file is actually
            # there — capture_plan tells us per spec.
            cap = {name: (action == 'copy') for name, _d, _de, action in self.df.capture_plan(rc)}
            for st in self.df.spec_states(rc):
                source = (f'{self._root_label(st.src_root)}/{st.src_rel}' if st.src_root is not None
                          else st.src_rel)
                cfg.append((rc, st.name, st.target, st.state, source, cap.get(st.name, False)))
        self.rows = cfg
        self.display = [('row', k) for k in range(len(cfg))]   # single group -> no dividers
        self.cur = max(0, min(self.cur, len(self.rows) - 1))

    def cur_row(self):
        return self.rows[self.cur] if 0 <= self.cur < len(self.rows) else None

    def driver_for(self, _rc):
        return self.df


class GlueScreen(_ContentRootLabelMixin):
    '''Shell-integration view over via:glue units — snippets GROUPED under each installed shell,
    with the shell-glue loader status as the section header. Ship->activate toggle (no capture): a
    snippet (e.g. fzf-glue) appears under every shell it ships a variant for, and each per-shell row
    is INDEPENDENTLY activatable — acting on a row activates/deactivates that snippet for ITS shell
    only (so activating fzf under bash doesn't light up fzf under fish).'''
    def __init__(self, ctx, *, load=True):
        self.ctx = ctx
        self.cur = 0
        self.top = 0
        self.hscroll = 0
        self.dirty = set()
        if load:                         # (a Theme preview sample fills its own rows: no real load)
            self.reload()

    def reload(self):
        from .. import actions
        from ..drivers import get_driver
        _df, units = actions.dotfiles_units(self.ctx)
        self.units = [rc for rc in units if rc.driver == 'glue']
        self.gd = get_driver('glue', self.ctx.runner, self.ctx.paths)
        shells = self.gd._installed_shells()                 # section order
        by_shell = {s: [] for s in shells}                   # shell -> [(rc, comp, tgt, state, src)]
        loader = {}                                          # shell -> loader-on|loader-off
        for rc in self.units:
            for st in self.gd.spec_states(rc):
                if st.name.endswith(' loader'):              # the shell-glue substrate (loader: all)
                    loader[st.name.split()[0]] = st.state
                    continue
                sh = st.name.rsplit('@', 1)[1] if '@' in st.name else None   # a snippet row 'glue@shell'
                if sh in by_shell:
                    src = (f'{self._root_label(st.src_root)}/{st.src_rel}' if st.src_root is not None
                           else st.src_rel)
                    by_shell[sh].append((rc, rc.comp, st.target, st.state, src))
        self.loader = loader
        user_by_shell = self._user_rows(by_shell)
        self.rows = []                                       # (rc, comp, tgt, state, src, shell[, True])
        self.display = []                                    # ('hdr', shell, loader_state) | ('row', idx)
        for sh in shells:
            self.display.append(('hdr', sh, loader.get(sh)))
            for rc, comp, tgt, state, src in sorted(by_shell[sh], key=lambda r: r[1]):
                self.rows.append((rc, comp, tgt, state, src, sh))
                self.display.append(('row', len(self.rows) - 1))
            for row in user_by_shell.get(sh, ()):            # then YOUR glue (user.d), after the shipped
                self.rows.append(row)
                self.display.append(('row', len(self.rows) - 1))
        self.cur = max(0, min(self.cur, len(self.rows) - 1))

    def _user_rows(self, by_shell):
        '''{shell: [user-glue row]} for the installed shells — `glue add` snippets and activated
        staged installer blocks (the user.d namespace, Glue.user_glue_entries). A user row is a 7-tuple
        flagged True: (None, '(user) <name>', conf.d link, 'linked'|'unlinked', source, shell, True).
        They aren't units: configsys links them but never edits them.'''
        out = {}
        try:
            entries = self.gd.user_glue_entries() if self.gd is not None else []
        except Exception:                                    # noqa: BLE001 — never brick the page
            entries = []
        roots = []
        try:
            roots = list(self.gd._user_glue_roots())
        except Exception:                                    # noqa: BLE001
            pass
        for shell, src, link, state in entries:
            if shell not in by_shell:                        # a shell that isn't installed here
                continue
            label = str(src)
            for root in roots:
                try:
                    label = f'{self._root_label(root)}/{src.relative_to(root)}'
                    break
                except (ValueError, AttributeError, TypeError):
                    continue
            out.setdefault(shell, []).append(
                (None, f'(user) {src.stem}', str(link), state, label, shell, True))
        return out

    def cur_row(self):
        return self.rows[self.cur] if 0 <= self.cur < len(self.rows) else None

    def driver_for(self, _rc):
        return self.gd


# Columns: COMPONENT, STATE, LINK (the ~/… symlink location on your system), SOURCE (the managed
# content it points at — the store/.cfs).
_DF_HEADERS = ['component', 'state', 'link', 'source']


def _df_cells(row):
    '''The four column strings for a dotfiles (config) row — the STATE column shows the collapsed
    user-facing state (managed / unmanaged / no config). `!` flags a real on-system file configsys
    does NOT manage (linking would refuse; capture it first).'''
    from ..drivers.dotfiles import config_display_state
    rc, _name, tgt, state, source, cap = row
    mark = '!' if state == 'unmanaged' else ' '
    return [rc.comp, f'{mark} {config_display_state(state, cap)}', str(tgt), source]


def _is_user_glue(row):
    '''True for a USER glue row (the user.d namespace: `glue add` / an activated staged block) — not a
    component's shipped snippet. Flagged by a 7th tuple element (see GlueScreen._user_rows).'''
    return len(row) > 6 and bool(row[6])


def _glue_cells(row):
    '''The four column strings for a glue row — state in the active/available/inactive vocabulary
    (a user snippet whose conf.d link is missing reads 'inactive').'''
    comp, tgt, state, src = row[1], row[2], row[3], row[4]
    return [comp, _GLUE_STATE_LABEL.get(state, 'inactive' if state == 'unlinked' else state),
            str(tgt), src]
