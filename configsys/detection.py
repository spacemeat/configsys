'''detection.py — the detection tier (routing-overhaul Phase 1).

Resolution is otherwise blind to the machine's disk: it picks the default method/provider even when
a different-but-valid one is already installed, "pushing" you toward a fresh install you never asked
for. This computes SOFT pins from a batched installed-enumeration and hands them to a second resolve
pass, layered BELOW your own pins — so precedence stays: explicit pin > detected-installed > default.

Two kinds of adoption:
  * method   — a resolved component installed via a NON-resolved (but valid) method  -> pin that via.
  * provider — a capability whose resolved provider isn't installed while ANOTHER valid provider IS
               -> pin that provider (the cuda-toolkit-11-vs-12 case).

Empty when nothing relevant is installed, so resolution is byte-identical on a fresh machine (and the
golden, which never runs this — it lives in the app pipeline, not the pure Resolver). Cheap: one
`installed_index()` per package-manager driver (batched), path/build drivers use their fast
per-method get_version; no `get_latest` (no network).
'''

import threading

from .adapt import to_resolved_component
from .drivers import get_driver
from .resolve import candidate_bindings, unit_for_binding, via_representatives

_cache_lock = threading.Lock()                  # guards the shared installed-index cache under the
#                                                 parallel method-detection loop (below)


def _enum_index(cache, drv):
    with _cache_lock:
        if drv.name in cache:
            return cache[drv.name]
    try:                                        # enumerate OUTSIDE the lock (a slow subprocess) — a
        idx = drv.installed_index()             # rare concurrent double-enum is wasteful but harmless
    except Exception:                           # noqa: BLE001 — a flaky lister must not brick resolve
        idx = None
    with _cache_lock:
        return cache.setdefault(drv.name, idx)


def _installed_via(ctx, comp, cx, cache):
    '''The via `comp` is installed under here (any of its candidate methods), else None. Batched.'''
    r = ctx.routes
    try:
        reps = via_representatives(candidate_bindings(comp, r.cascade, cx, None), r.cascade)
    except Exception:                           # noqa: BLE001
        return None
    for b in reps:
        unit = unit_for_binding(comp, b, r.cascade, r.block, r.overrides)
        if unit is None:
            continue
        rc = to_resolved_component(unit)
        drv = get_driver(rc.driver, ctx.runner, ctx.paths)
        if drv is None:
            continue
        try:
            idx = _enum_index(cache, drv)
            ver = idx.get(drv.index_key(rc)) if idx is not None else drv.get_version(rc)
        except Exception:                       # noqa: BLE001
            ver = None
        if ver is not None:
            return rc.via
    return None


def detect_pins(ctx, units, progress=None):
    '''Soft {name-or-cap: via-or-provider} pins biasing resolution toward installed reality. User-
    pinned components/caps are left alone. Returns {} when nothing applies (fresh machine).
    `progress(done, total)` is called as work completes — across BOTH sub-phases (per-driver
    installed-set enumeration, then per-unit method detection) as one combined counter — so the splash
    tracks the whole (subprocess-bound) detection phase, not just its fast head.'''
    from .installState import _parallel_map
    r = ctx.routes
    cx = r.cascade.context(r.block, r.version, r.cpu)
    user_pins = ctx.config.pins()
    cache = {}
    pins = {}

    unit_list = list(units.values())
    drivers = list({rc.driver for rc in unit_list})
    total = len(drivers) + len(unit_list)          # one combined progress space over both sub-phases
    base = [0]

    def relay(done, _n):
        if progress:
            progress(base[0] + done, total)

    # Sub-phase 1 — pre-warm the per-driver installed_index cache CONCURRENTLY. Otherwise it fills
    # LAZILY and serially — the method loop below would call installed_index the first time it hit each
    # driver, summing the same slow enumerations (apt dpkg-query, npm/pipx/pip/flatpak list). Up-front
    # and parallel collapses that to the slowest one.
    def _enum(name):
        drv = get_driver(name, ctx.runner, ctx.paths)
        if drv is None:
            return name, None
        try:
            return name, drv.installed_index()
        except Exception:                           # noqa: BLE001 — a flaky lister must not brick resolve
            return name, None
    for name, idx in _parallel_map(_enum, drivers, progress=relay):
        cache[name] = idx
    base[0] = len(drivers)

    # Sub-phase 2 — method detection, PARALLEL. Non-package-manager drivers (tarball/appImage/source/
    # script/…) have no installed_index, so `_installed_via` falls to a per-unit `get_version`
    # subprocess; run those concurrently (they're read-only, captured I/O) instead of summing serially.
    def _method(rc):
        name = rc.comp
        if name in user_pins:
            return None
        comp = r.components.get(name)
        if comp is None or not comp.bindings:
            return None
        inst_via = _installed_via(ctx, comp, cx, cache)
        return (name, inst_via) if (inst_via and inst_via != rc.via) else None
    for res in _parallel_map(_method, unit_list, progress=relay):
        if res:
            pins[res[0]] = res[1]
    base[0] += len(unit_list)

    # -- provider detection: a cap resolved to X, but a different valid provider Y is installed --
    prov_index = {}                                     # cap -> [component names that provide it]
    for cname, comp in r.components.items():
        for cap in getattr(comp, 'provides', ()):
            prov_index.setdefault(cap, []).append(cname)
    resolved_names = {rc.comp for rc in units.values()}
    # caps "in play" = those a RESOLVED provider satisfies (its `provides:`) — keyed off the resolved
    # unit, NOT the requiring edge, since binding-level `requires:` are stripped from rc.fields (they
    # are resolver keys). So cuda-toolkit-12 being resolved (blender's dep) puts `cuda-toolkit` in play.
    caps_in_play = set()
    for rc in units.values():
        comp = r.components.get(rc.comp)
        if comp is not None:
            caps_in_play.update(comp.provides)
    for cap in caps_in_play:
        if cap in user_pins or cap in pins:
            continue
        providers = prov_index.get(cap, [])
        if len(providers) < 2:
            continue
        resolved_prov = next((p for p in providers if p in resolved_names), None)
        # if the resolved provider is itself installed, keep it — nothing to adopt.
        if resolved_prov and _installed_via(ctx, r.components[resolved_prov], cx, cache):
            continue
        for p in providers:
            if p == resolved_prov:
                continue
            comp_p = r.components.get(p)
            if comp_p is not None and _installed_via(ctx, comp_p, cx, cache):
                pins[cap] = p
                break
    return pins
