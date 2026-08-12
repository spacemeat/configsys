'''installState.py — reconcile resolved components against the live system.

For each resolved unit, dispatch to its driver (if supported) to read installed
version, latest/candidate version, and native lock state; union the native lock
with the ledger's lock intent. Unsupported drivers (not yet implemented in M1)
degrade to an 'unsupported' state rather than crashing. Inspection is read-only.
'''

import time
from dataclasses import dataclass
from typing import Optional

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

    def inspect(self, units, progress=None, reuse=None, dirty=None):
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
        batch = self._build_batch(to_probe)
        out, total = {}, len(units)
        for i, (key, rc) in enumerate(units.items(), 1):
            if key in reuse and key not in dirty:
                st = reuse[key]
                st.component = rc                 # keep the cached probe, refresh resolution facts
                out[key] = st
                continue
            t0 = time.perf_counter()
            st = self.inspect_one(rc, batch.get(rc.driver))
            out[key] = st
            if progress is not None:
                progress(i, total, key, st, (time.perf_counter() - t0) * 1000)
        return out

    def _build_batch(self, units):
        '''{driver_name: batch-context} — one pre-fetch per DRIVER present in `units`, for drivers
        that implement `batch_index(names)`. The context is opaque (only that driver reads it) and
        lets its read ops answer in-process instead of a subprocess per unit. A driver that has no
        batch_index, or whose batch probe fails, is simply absent -> inspect_one falls back.'''
        by_driver = {}
        for rc in units.values():
            by_driver.setdefault(rc.driver, set()).add(rc.name)
        batch = {}
        for driver, names in by_driver.items():
            drv = get_driver(driver, self.runner, self.paths)
            fn = getattr(drv, 'batch_index', None)
            if fn is None:
                continue
            try:
                bi = fn(sorted(names))
            except Exception:  # noqa: BLE001 — batching is an optimization, never fatal
                bi = None
            if bi is not None:
                batch[driver] = bi
        return batch

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
    from .adapt import to_resolved_component
    from .resolve import candidate_bindings, unit_for_binding, via_representatives
    r = ctx.routes
    cx = r.cascade.context(r.block, r.version, r.cpu)
    enum = {}                                       # driver name -> installed_index() dict or None

    def index_of(drv):
        if drv.name not in enum:
            try:
                enum[drv.name] = drv.installed_index()
            except Exception:                       # noqa: BLE001 - a flaky lister must not brick inspect
                enum[drv.name] = None
        return enum[drv.name]

    for st in states.values():
        managed = st.component
        comp = r.components.get(managed.comp)
        if comp is None or not comp.bindings:
            continue
        try:
            reps = via_representatives(candidate_bindings(comp, r.cascade, cx, None), r.cascade)
        except Exception:                           # noqa: BLE001
            continue
        if len(reps) < 2:
            continue                                # only one method here -> nothing else to find
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
    return states
