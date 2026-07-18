'''installState.py — reconcile resolved components against the live system.

For each resolved unit, dispatch to its driver (if supported) to read installed
version, latest/candidate version, and native lock state; union the native lock
with the ledger's lock intent. Unsupported families (not yet implemented in M1)
degrade to an 'unsupported' state rather than crashing. Inspection is read-only.
'''

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
            return 'unsupported'
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
    def __init__(self, runner, ledger=None, paths=None):
        self.runner = runner
        self.ledger = ledger if ledger is not None else Ledger()
        self.paths = paths

    def inspect(self, units):
        '''units: {key: ResolvedComponent} -> {key: ComponentState}.'''
        return {key: self.inspect_one(rc) for key, rc in units.items()}

    def inspect_one(self, rc):
        led_lock = self.ledger.is_locked(rc.key)
        managed = self.ledger.is_managed(rc.key)
        fam = get_driver(rc.driver, self.runner, self.paths)

        if fam is None:
            return ComponentState(
                component=rc, supported=False, present=False,
                installed_version=None, latest_version=None,
                locked=led_lock, lock_source=('ledger' if led_lock else None),
                managed=managed,
                error=f'driver "{rc.driver}" not yet supported')

        try:
            version = fam.get_version(rc)
            latest = fam.get_latest(rc)
            native_lock = fam.is_locked(rc)
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
            scope=fam.scope(rc))
