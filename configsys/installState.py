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

    @property
    def key(self):
        return self.component.key

    @property
    def outdated(self):
        return bool(self.present and self.installed_version
                    and self.latest_version
                    and self.installed_version != self.latest_version)

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
        out, total = {}, len(units)
        for i, (key, rc) in enumerate(units.items(), 1):
            if key in reuse and key not in dirty:
                st = reuse[key]
                st.component = rc                 # keep the cached probe, refresh resolution facts
                out[key] = st
                continue
            t0 = time.perf_counter()
            st = self.inspect_one(rc)
            out[key] = st
            if progress is not None:
                progress(i, total, key, st, (time.perf_counter() - t0) * 1000)
        return out

    def inspect_one(self, rc):
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
