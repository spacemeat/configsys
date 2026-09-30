'''installState.py — reconcile resolved components against the live system.

For each resolved unit, dispatch to its driver (if supported) to read installed
version, latest/candidate version, and native lock state; union the native lock
with the ledger's lock intent. Unsupported drivers (not yet implemented in M1)
degrade to an 'unsupported' state rather than crashing. Inspection is read-only.
'''

import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional


def _parallel_map(fn, items, progress=None):
    '''Map `fn` over `items` CONCURRENTLY — for I/O-bound, captured (terminal-untouching) probes, so
    wall time is the slowest single call, not the sum. Serial for <=1 item (no pool overhead). Order
    of results is unspecified (callers are order-independent). `progress(done, total)`, if given, is
    called AS EACH item completes (not at the end) — so a caller can drive a live progress bar through
    a slow parallel enumeration. Exceptions are the callee's problem — `fn` here always returns.'''
    n = len(items)
    if n <= 1:
        out = [fn(it) for it in items]
        if progress:
            progress(n, n)                     # 0 or 1 item: one terminal tick
        return out
    from concurrent.futures import as_completed
    out = []
    with ThreadPoolExecutor(max_workers=min(8, n)) as ex:
        futs = [ex.submit(fn, it) for it in items]
        for done, fut in enumerate(as_completed(futs), 1):
            out.append(fut.result())
            if progress:
                progress(done, n)              # fires as real work finishes -> the bar tracks it
    return out

from .componentObj import ResolvedComponent
from .drivers import get_driver
from .ledger import Ledger


# a Go pseudo-version: vX.Y.Z-[pre.0.]yyyymmddhhmmss-<12 hex> (an untagged module's snapshot)
_PSEUDO = re.compile(r'^v?\d+\.\d+\.\d+-(?:.*\.)?(\d{14})-[0-9a-f]{12}$')


def _pseudo_ts(v):
    '''The 14-digit UTC commit timestamp of a Go pseudo-version, else None.'''
    m = _PSEUDO.match(str(v or ''))
    return m.group(1) if m else None


@dataclass
class ComponentState:
    component: ResolvedComponent
    supported: bool
    present: bool
    installed_version: Optional[str]
    latest_version: Optional[str]
    locked: bool
    lock_source: Optional[str]   # 'native' | 'ledger' | 'both' | None
    managed: bool
    error: Optional[str]
    scope: Optional[str] = None  # 'user' | 'system' | None (unsupported driver)
    untrusted: bool = False      # driver exists but its plugin isn't trusted yet (not just unknown)
    also_present: tuple = ()     # coexisting installs via OTHER methods: ((via, package, version), ...)
    holds_version: bool = True   # driver can hold/pin a version -> lock/set-version are offered
    outdated_override: Optional[bool] = None   # a driver's own outdated verdict (flatpak: commit-based),
                                               # overriding the version-string compare; None -> use it
    upstream_version: Optional[str] = None     # newest upstream release of a RECIPE-PINNED method
                                               # (binding `upstream:`); advisory, never "latest"

    @property
    def key(self):
        return self.component.key

    @property
    def outdated(self):
        if not self.present:
            return False
        # A driver whose real update signal isn't the version string (flatpak: a same-version rebuild
        # is a new COMMIT the software store flags) answers authoritatively; trust that over the strings.
        if self.outdated_override is not None:
            return self.outdated_override
        if not (self.installed_version and self.latest_version):
            return False
        # compare across schemes: an apt version `26.5.6-1` and a github tag `v26.5.6` are the SAME
        # upstream version — a raw string `!=` would falsely flag it outdated. Normalize both; only
        # a strictly newer upstream version is "outdated". Unparseable -> conservative string diff.
        from .osversion import parse_loose
        # Go pseudo-versions (an untagged module, e.g. discordo: 0.0.0-20260926000522-08b41176c060)
        # share the same numeric base, so compare their commit TIMESTAMPS — else every snapshot reads
        # "current" forever
        pi, pl = _pseudo_ts(self.installed_version), _pseudo_ts(self.latest_version)
        if pi and pl:
            return pi < pl
        li, ll = parse_loose(self.installed_version), parse_loose(self.latest_version)
        if li is not None and ll is not None:
            return li < ll
        return self.installed_version != self.latest_version

    @property
    def recipe_behind(self):
        '''True when this method builds a recipe-PINNED version and upstream has released a newer
        one. NOT outdated: an upgrade rebuilds the pin; reaching the new release needs a new recipe.'''
        if not (self.upstream_version and self.latest_version):
            return False
        from .osversion import parse_loose
        lu, ll = parse_loose(self.upstream_version), parse_loose(self.latest_version)
        return lu is not None and ll is not None and ll < lu

    @property
    def status(self):
        if not self.supported:
            return 'untrusted' if self.untrusted else 'unsupported'
        if self.error:
            return 'error'
        if not self.present:
            return 'missing'
        if self.locked:
            return 'locked'
        if self.outdated:
            return 'outdated'
        return 'installed'


class InstallState:
    def __init__(self, runner, ledger=None, paths=None, pending_vias=()):
        self.runner = runner
        self.ledger = ledger if ledger is not None else Ledger()
        self.paths = paths
        # via names a declared code plugin WOULD provide but that isn't loaded (untrusted /
        # ABI-incompatible) — lets a missing driver read as "untrusted" rather than "unsupported".
        self.pending_vias = set(pending_vias)

    def inspect(self, units, progress=None, reuse=None, dirty=None, batch_progress=None):
        '''units: {key: ResolvedComponent} -> {key: ComponentState}. `progress`, if given, is
        called (i, total, key, state, ms) after each freshly-probed unit — the per-unit state
        check is the slow part, so this lets the caller show motion during a long load.

        PARTIAL requery: `reuse` (a prior {key: state}) lets an unchanged unit skip the probe —
        its cached state is kept (its resolution facts refreshed to the new rc). `dirty` forces a
        re-probe of specific keys (the ones an op just changed). So a pin change re-probes only
        the newly-appearing units, and an execute re-probes only what it touched.'''
        reuse, dirty = reuse or {}, dirty or set()
        # BATCH PREPASS: for the units we'll actually probe, let each driver pre-fetch its enumerable
        # state ONCE (one `dpkg-query -W` / `apt-mark showhold` / `apt-cache policy pkg...` instead of
        # three subprocesses per unit) — the startup cost was ~440 serial spawns. Drivers without a
        # batch_index simply don't participate and fall back to per-unit probes.
        to_probe = {k: rc for k, rc in units.items() if k not in reuse or k in dirty}
        batch = self._build_batch(to_probe, progress=batch_progress)
        # expose the batched drivers' full installed maps ({driver: {index_key: version}}) so callers
        # (the TUI install overlay) can reuse this already-paid enumeration instead of re-listing.
        self.enum = {}
        for dname, ctx in batch.items():
            drv = get_driver(dname, self.runner, self.paths)
            idx = drv.batch_installed_index(ctx) if drv is not None else None
            if idx:
                self.enum[dname] = idx
        out, total = {}, len(units)
        for key, rc in units.items():             # reused units keep their cached probe, no work
            if key in reuse and key not in dirty:
                st = reuse[key]
                st.component = rc                 # refresh resolution facts on the cached state
                out[key] = st
        # Probe the rest CONCURRENTLY — inspect_one is read-only, captured (stdin=DEVNULL) I/O per
        # unit, so the non-batched drivers' per-unit probes overlap instead of summing. `progress`
        # still fires once per unit AS IT COMPLETES (on this thread, via as_completed), so the splash
        # keeps animating; only the probes themselves run on the pool.
        to_do = [(k, rc) for k, rc in units.items() if k not in reuse or k in dirty]
        if len(to_do) <= 1:
            for i, (key, rc) in enumerate(to_do, 1):
                t0 = time.perf_counter()
                out[key] = st = self.inspect_one(rc, batch.get(rc.driver))
                if progress is not None:
                    progress(i, total, key, st, (time.perf_counter() - t0) * 1000)
        else:
            from concurrent.futures import as_completed
            t0 = time.perf_counter()
            with ThreadPoolExecutor(max_workers=min(8, len(to_do))) as ex:
                futs = {ex.submit(self.inspect_one, rc, batch.get(rc.driver)): key
                        for key, rc in to_do}
                for i, fut in enumerate(as_completed(futs), 1):
                    key = futs[fut]
                    out[key] = st = fut.result()
                    if progress is not None:
                        progress(i, total, key, st, (time.perf_counter() - t0) * 1000)
        return out

    def _build_batch(self, units, progress=None):
        '''{driver_name: batch-context} — one pre-fetch per DRIVER present in `units`, for drivers
        that implement `batch_index(rcs)` (given the units' ResolvedComponents, so a driver can read
        whatever fields it needs — e.g. flatpak's `hub`). The context is opaque (only that driver
        reads it) and lets its read ops answer in-process instead of a subprocess per unit. A driver
        with no batch_index, or whose batch probe fails, is simply absent -> inspect_one falls back.'''
        by_driver = {}
        for rc in units.values():
            by_driver.setdefault(rc.driver, []).append(rc)

        def probe(item):
            driver, rcs = item
            drv = get_driver(driver, self.runner, self.paths)
            fn = getattr(drv, 'batch_index', None)
            if fn is None:
                return driver, None
            try:
                return driver, fn(rcs)
            except Exception:  # noqa: BLE001 — batching is an optimization, never fatal
                return driver, None

        # Each driver's batch_index is independent, captured (stdin=DEVNULL, terminal-untouching) I/O —
        # so run them CONCURRENTLY: the prepass wall time drops from the SUM of per-driver enumerations
        # (flatpak remote-ls + npm ls + apt + pipx/pip …) to the slowest single one.
        return {d: bi for d, bi in _parallel_map(probe, list(by_driver.items()), progress=progress)
                if bi is not None}

    def inspect_one(self, rc, batch=None):
        led_lock = self.ledger.is_locked(rc.key)
        managed = self.ledger.is_managed(rc.key)
        drv = get_driver(rc.driver, self.runner, self.paths)

        if drv is None:
            untrusted = rc.driver in self.pending_vias
            msg = (f'driver "{rc.driver}" comes from a plugin you haven\'t trusted yet — '
                   'approve it with `configsys plugin trust <name>` (see `configsys plugin list`)'
                   if untrusted else f'driver "{rc.driver}" not yet supported')
            return ComponentState(
                component=rc, supported=False, present=False,
                installed_version=None, latest_version=None,
                locked=led_lock, lock_source=('ledger' if led_lock else None),
                managed=managed, untrusted=untrusted, error=msg)

        drv._batch = batch                        # per-inspect batch context (None -> per-unit probes)
        try:
            version, detected_scope = drv.get_installed(rc)   # reality: version + where installed
            latest = drv.get_latest(rc)
            native_lock = drv.is_locked(rc)
            # let a driver override the version-string outdated compare (flatpak: commit-based)
            outdated_override = drv.outdated_signal(rc) if version is not None else None
            upstream = drv.upstream_version(rc) if rc.fields.get('upstream') else None
        except Exception as e:  # a driver op blew up; report, don't crash the sweep
            return ComponentState(
                component=rc, supported=True, present=False,
                installed_version=None, latest_version=None,
                locked=led_lock, lock_source=('ledger' if led_lock else None),
                managed=managed, error=str(e))

        # a driver that can't hold a version (rolling: pacman/apk) never reads as locked — a stale
        # ledger entry from before this was disallowed is ignored, not shown as a lock we can't keep.
        holds = getattr(drv, 'holds_version', True)
        locked = holds and (native_lock or led_lock)
        if not holds:
            lock_source = None
        elif native_lock and led_lock:
            lock_source = 'both'
        elif native_lock:
            lock_source = 'native'
        elif led_lock:
            lock_source = 'ledger'
        else:
            lock_source = None

        return ComponentState(
            component=rc, supported=True, present=version is not None,
            installed_version=version, latest_version=latest,
            locked=locked, lock_source=lock_source, managed=managed, error=None,
            holds_version=holds, outdated_override=outdated_override, upstream_version=upstream,
            scope=detected_scope or drv.scope(rc))   # detected reality if installed, else target


def recipe_pin_text(pinned, upstream):
    '''The one wording for a recipe-pinned method behind upstream (TUI detail line, `versions`).'''
    from .osversion import clean_version
    pinned, upstream = clean_version(pinned), clean_version(upstream)
    return (f'recipe pins {pinned}; upstream is {upstream} — a new version needs a NEW RECIPE '
            f'(routes, possibly a new toolchain), not an upgrade')


def detect_coexisting(ctx, states):
    '''Augment each state with `also_present`: coexisting installs found via the component's OTHER
    (non-managed) candidate methods — the "walk up to an existing machine and see EVERYTHING that's
    installed" pass. Cheap: package-manager drivers are enumerated ONCE each (batched
    `installed_index`), path/build drivers use their fast per-method get_version; NO get_latest (no
    network — "outdated" is only for the managed method). Mutates and returns `states`.'''
    from . import probecache
    from .adapt import to_resolved_component
    from .resolve import candidate_bindings, unit_for_binding, via_representatives
    r = ctx.routes
    cx = r.context()
    probes = probecache.of(ctx)                     # shared with the detection tier; kept across a reload

    def _one(st):
        managed = st.component
        comp = r.components.get(managed.comp)
        if comp is None or not comp.bindings:
            return
        try:
            reps = via_representatives(candidate_bindings(comp, r.cascade, cx, None), r.cascade)
        except Exception:                           # noqa: BLE001
            return
        if len(reps) < 2:
            return                                  # only one method here -> nothing else to find
        also = []
        for b in reps:
            if b.via == managed.via:
                continue                            # the managed method is already this state
            unit = unit_for_binding(comp, b, r.cascade, r.block, r.overrides)
            if unit is None:
                continue
            rc = to_resolved_component(unit)
            drv = get_driver(rc.driver, ctx.runner, ctx.paths)
            if drv is None:
                continue
            try:
                ver = probes.version(drv, rc)
            except Exception:                       # noqa: BLE001
                ver = None
            if ver is not None:
                also.append((rc.via, rc.name, ver))
        if also:
            st.also_present = tuple(also)

    # per-state candidate probes (get_version for non-indexed drivers) are subprocess-bound and
    # independent -> run concurrently, like the inspect + detection passes.
    _parallel_map(_one, list(states.values()))
    return states


_SWAP_INSTALLISH = ('install', 'upgrade', 'set-version')


def superseded_installs(ctx, target_rc):
    '''ResolvedComponents for `target_rc`'s component that are CURRENTLY installed via a DIFFERENT
    method than target_rc's — the OLD installs a method-switch supersedes. Returns [(rc, version), …],
    empty when there's nothing to swap (the common case). Best-effort probes of the component's other
    candidate bindings (the same walk `detect_coexisting` does, targeted at ONE component).'''
    from .adapt import to_resolved_component
    from .resolve import candidate_bindings, unit_for_binding, via_representatives
    r = ctx.routes
    comp = r.components.get(target_rc.comp)
    if comp is None or not comp.bindings:
        return []
    cx = r.context()
    try:
        reps = via_representatives(candidate_bindings(comp, r.cascade, cx, None), r.cascade)
    except Exception:                               # noqa: BLE001 — a routing hiccup means no swap
        return []
    out = []
    for b in reps:
        if b.via == target_rc.via:
            continue                                # the method we're keeping
        unit = unit_for_binding(comp, b, r.cascade, r.block, r.overrides)
        if unit is None:
            continue
        rc = to_resolved_component(unit)
        if rc.key == target_rc.key:
            continue
        drv = get_driver(rc.driver, ctx.runner, ctx.paths)
        if drv is None:
            continue
        try:
            ver = drv.get_version(rc)
        except Exception:                           # noqa: BLE001 — a flaky probe just finds nothing
            ver = None
        if ver is not None:
            out.append((rc, ver))
    return out


def plan_with_swaps(ctx, base_plan, units):
    '''Inject a `remove` of any OLD-method install superseded by an install/upgrade target in
    `base_plan` — the method-switch swap. Remove-before-install ordering is `expand_plan`'s job (it
    promotes a remove whose component also has an install to run first). Returns (plan, units) with
    the old units merged in. A no-op unless a target is also installed via another method.'''
    plan = list(base_plan)
    units = dict(units)
    seen = {k for _op, k, _rc in base_plan}
    for op, _key, rc in base_plan:
        if op not in _SWAP_INSTALLISH or rc is None:
            continue
        for old_rc, _ver in superseded_installs(ctx, rc):
            if old_rc.key in seen:
                continue
            seen.add(old_rc.key)
            units[old_rc.key] = old_rc
            plan.append(('remove', old_rc.key, old_rc))
    return plan_companion_cleanup(ctx, plan, units)


def plan_companion_cleanup(ctx, plan, units):
    '''Remove the GLUE companions a removal leaves behind. A method's own glue (a binding-level
    `suggests:`, e.g. a source build's PATH snippet) must go when that method is switched away from,
    and a component's glue when the component itself is removed — else a stale snippet keeps putting
    the old install on PATH. Only glue (dotfiles/config links are left alone), only when installed,
    and never one still wanted: in the resolution of this machine's picks (minus components being
    removed outright) or of the plan's own install targets. Returns (plan, units).'''
    from .resolve import cap_names
    r = ctx.routes
    installing = {rc.comp for op, _k, rc in plan if op in _SWAP_INSTALLISH and rc is not None}
    removing = [(k, rc) for op, k, rc in plan if op == 'remove' and rc is not None]
    if not removing:
        return plan, units
    gone = {rc.comp for _k, rc in removing if rc.comp not in installing}   # removed OUTRIGHT
    caps = []
    for _k, rc in removing:
        comp = r.components.get(rc.comp)
        if comp is None:
            continue
        b = next((b for b in comp.bindings if b.via == (rc.via or None)), None)
        if b is not None:
            caps += cap_names(b.details.get('suggests'))      # this METHOD's companions
        if rc.comp in gone:
            caps += list(comp.suggests)                        # the component's own companions
    if not caps:
        return plan, units
    try:
        keep_names = [n for n in ctx.config.requested() if n not in gone] + sorted(installing)
        keep, _errs = r.resolve_resilient(keep_names)
    except Exception:                                           # noqa: BLE001 — unsure -> keep all
        return plan, units
    plan, units = list(plan), dict(units)
    seen = {k for _op, k, _rc in plan}
    for cap in dict.fromkeys(caps):
        try:
            cunits, _e = r.resolve_resilient([cap])
        except Exception:                                       # noqa: BLE001
            continue
        for ckey, crc in cunits.items():
            if crc.driver != 'glue' or crc.comp != cap or ckey in seen or ckey in keep:
                continue
            drv = get_driver('glue', ctx.runner, ctx.paths)
            try:
                present = drv is not None and drv.get_version(crc) is not None
            except Exception:                                   # noqa: BLE001
                present = False
            if present:
                seen.add(ckey)
                units[ckey] = crc
                plan.append(('remove', ckey, crc))
    return plan, units
