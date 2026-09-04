'''installState.py — reconcile resolved components against the live system.

For each resolved unit, dispatch to its driver (if supported) to read installed
version, latest/candidate version, and native lock state; union the native lock
with the ledger's lock intent. Unsupported drivers (not yet implemented in M1)
degrade to an 'unsupported' state rather than crashing. Inspection is read-only.
'''

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

    @property
    def key(self):
        return self.component.key

    @property
    def outdated(self):
        if not (self.present and self.installed_version and self.latest_version):
            return False
        # compare across schemes: an apt version `26.5.6-1` and a github tag `v26.5.6` are the SAME
        # upstream version — a raw string `!=` would falsely flag it outdated. Normalize both; only
        # a strictly newer upstream version is "outdated". Unparseable -> conservative string diff.
        from .osversion import parse_loose
        li, ll = parse_loose(self.installed_version), parse_loose(self.latest_version)
        if li is not None and ll is not None:
            return li < ll
        return self.installed_version != self.latest_version

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
        except Exception as e:  # a driver op blew up; report, don't crash the sweep
            return ComponentState(
                component=rc, supported=True, present=False,
                installed_version=None, latest_version=None,
                locked=led_lock, lock_source=('ledger' if led_lock else None),
                managed=managed, error=str(e))

        locked = native_lock or led_lock
        if native_lock and led_lock:
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
            scope=detected_scope or drv.scope(rc))   # detected reality if installed, else target


def detect_coexisting(ctx, states):
    '''Augment each state with `also_present`: coexisting installs found via the component's OTHER
    (non-managed) candidate methods — the "walk up to an existing machine and see EVERYTHING that's
    installed" pass. Cheap: package-manager drivers are enumerated ONCE each (batched
    `installed_index`), path/build drivers use their fast per-method get_version; NO get_latest (no
    network — "outdated" is only for the managed method). Mutates and returns `states`.'''
    import threading
    from .adapt import to_resolved_component
    from .resolve import candidate_bindings, unit_for_binding, via_representatives
    r = ctx.routes
    cx = r.cascade.context(r.block, r.version, r.cpu)
    enum = {}                                       # driver name -> installed_index() dict or None
    lock = threading.Lock()                         # guards `enum` under the parallel per-state loop

    def index_of(drv):
        with lock:
            if drv.name in enum:
                return enum[drv.name]
        try:                                        # enumerate outside the lock (slow subprocess)
            idx = drv.installed_index()
        except Exception:                           # noqa: BLE001 - a flaky lister must not brick inspect
            idx = None
        with lock:
            return enum.setdefault(drv.name, idx)

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
                idx = index_of(drv)
                ver = idx.get(drv.index_key(rc)) if idx is not None else drv.get_version(rc)
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
