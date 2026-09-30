'''probecache.py — read-only "what's installed" probes, shared and kept across a TUI reload.

Two passes of the load pipeline ask the machine the same questions: the detection tier (which
method/provider is ACTUALLY installed -> soft pins) and the coexistence pass (other methods'
installs -> "also present"). Both enumerate each package manager's installed set
(`installed_index()`: dpkg-query, flatpak/npm/pipx/pip list, …) and, for path/build drivers with no
index, run a per-unit `get_version` subprocess. They used to do it independently — and redo ALL of it
on every TUI reload (after a pin change or an execute), ~4s of the ~6s reload.

A ProbeCache holds those answers. The app keeps one on the context: a full load (startup, refresh)
starts a FRESH one, so it always reflects the machine; a reload that reuses inspection drops only
what its `dirty` units touched — the drivers that ran an op, and those components' per-unit
versions. A pin change with nothing executed invalidates nothing (installed reality didn't change).
Thread-safe: the passes probe in parallel.
'''

import threading


class ProbeCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._index = {}            # driver name -> installed_index() dict, or None (no index / failed)
        self._version = {}          # (driver name, unit key) -> get_version() result (None = absent)

    def installed_index(self, drv):
        '''drv.installed_index(), enumerated once per driver (a slow subprocess, run outside the lock —
        a rare concurrent double-enumeration is wasteful but harmless).'''
        name = _name(drv)
        with self._lock:
            if name in self._index:
                return self._index[name]
        try:
            idx = drv.installed_index()
        except Exception:                            # noqa: BLE001 — a flaky lister must not brick resolve
            idx = None
        with self._lock:
            return self._index.setdefault(name, idx)

    def version(self, drv, rc):
        '''The installed version of unit `rc` via `drv`, or None: from the driver's installed index when
        it has one, else a (cached) per-unit get_version.'''
        idx = self.installed_index(drv)
        if idx is not None:
            return idx.get(drv.index_key(rc))
        key = (_name(drv), rc.key)
        with self._lock:
            if key in self._version:
                return self._version[key]
        try:
            ver = drv.get_version(rc)
        except Exception:                            # noqa: BLE001
            ver = None
        with self._lock:
            return self._version.setdefault(key, ver)

    def invalidate(self, unit_keys):
        '''Forget what the given units (`driver\\comp` keys — the ops just run) may have changed: their
        drivers' installed indexes (a package op can move any of that manager's packages), and those
        components' per-unit versions. A `system-updates\\<mgr>` key (a bulk upgrade) drops <mgr>'s index.'''
        drivers, comps = set(), set()
        for k in unit_keys or ():
            drv, _, comp = str(k).partition('\\')
            if drv == 'system-updates':              # a bulk upgrade of manager <comp>: its whole index
                drivers.add(comp)
                continue
            drivers.add(drv)
            comps.add(comp)
        if not drivers:
            return
        with self._lock:
            for d in drivers:
                self._index.pop(d, None)
            # an unindexed probe (tarball/script/…) is per UNIT: drop just the touched components'
            # (every method's — a method switch's removed old-method unit is in the plan too)
            for key in [kv for kv in self._version if kv[1].partition('\\')[2] in comps]:
                del self._version[key]


def _name(drv):
    return getattr(drv, 'name', None) or type(drv).__name__


def of(ctx):
    '''The context's shared ProbeCache — or a fresh one for a bare/test context that carries none.'''
    pc = getattr(ctx, '_probes', None)
    return pc if pc is not None else ProbeCache()
