'''versionreport.py — per-install-method version visibility.

For a component, report what version EACH candidate install method (native / tarball / source /
flatpak / …) would install here, mark the default and any installed method, and flag methods that
lag the newest available ("tip"). Read-only substrate shared by `configsys versions`, the TUI
version panel, and (later) version-constrained requires.

It reuses each driver's `get_latest` ("what would this method install"). Native `get_latest`
queries the box's package manager and is slow, so latest results are cached machine-locally with a
TTL (`state_dir/method-versions.hu`); `refresh=True` bypasses. Installed versions (`get_version`)
are read live — they must be current right after an install/remove.
'''

import time
from dataclasses import dataclass, field

from .adapt import to_resolved_component
from .drivers import get_driver
from .errors import ConfigError
from .osversion import parse_loose
from .resolve import ResolveError, candidate_bindings, select_binding, unit_for_binding
from .troveio import emit_hu, load

LATEST_TTL = 86400  # 24h — a method's available version drifts slowly


@dataclass
class MethodVersion:
    via: str                     # the install method (native, tarball, source, …)
    driver: str                  # concrete driver (native -> apt/dnf/…)
    package: str                 # the package/dist identifier the driver operates on
    latest: str = None           # what this method would install now (get_latest, cached)
    installed: str = None        # this method's installed version, if installed (live)
    is_default: bool = False     # the method that resolves by default here
    is_pinned: bool = False      # a binding-pin selects this method
    meets_min: bool = None       # vs a floor (None = no floor asked, or unparseable)
    lags_tip: bool = False       # latest < tip (the newest across methods here)


@dataclass
class VersionReport:
    name: str
    methods: list = field(default_factory=list)
    tip: str = None              # newest available across methods
    min_version: str = None
    default_meets_min: bool = None   # does the DEFAULT method clear the floor?


# -- machine-local cache of get_latest results (keyed by unit key `driver\comp`) -----------------

class _LatestCache:
    def __init__(self, records=None):
        self.records = dict(records) if records else {}

    @classmethod
    def load(cls, paths):
        p = paths.method_versions_file
        if not p.exists() or not p.read_text(encoding='utf-8-sig').strip():
            return cls({})
        try:
            trove = load(p)
        except ConfigError:
            return cls({})
        root = trove.root
        recs = {}
        for i in range(root.num_children):
            ch = root[i]
            ver = ch['version'].value if ch['version'] is not None else None
            fetched = ch['fetched'].value if ch['fetched'] is not None else '0'
            try:
                fetched = float(fetched)
            except (TypeError, ValueError):
                fetched = 0.0
            recs[ch.key] = {'version': ver, 'fetched': fetched}
        return cls(recs)

    def save(self, paths):
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        obj = {k: {'version': r['version'] or '', 'fetched': repr(r['fetched'])}
               for k, r in sorted(self.records.items())}
        paths.method_versions_file.write_text(emit_hu(obj), encoding='utf-8')

    def get(self, key, now, ttl):
        r = self.records.get(key)
        return r if (r and now - r['fetched'] <= ttl) else None

    def set(self, key, version, now):
        self.records[key] = {'version': version, 'fetched': now}


def _cached_latest(cache, rc, drv, refresh, now):
    '''get_latest for a method, via the machine-local cache. A cache miss/expiry queries the driver
    (guarded — a probe failure is just "unknown", never fatal). "Unknown" (None/empty) is NEVER
    cached, and a cached EMPTY is treated as a miss — so a method whose driver only later learns to
    report a version (e.g. flatpak gaining get_latest) self-heals on the next read instead of being
    stuck on a stale blank until the TTL expires.'''
    if not refresh:
        hit = cache.get(rc.key, now, LATEST_TTL)
        if hit and hit['version']:
            return hit['version']
    ver = _safe(drv.get_latest, rc) if drv is not None else None
    if ver:                          # only cache a real answer; retry "unknown" next time
        cache.set(rc.key, ver, now)
    return ver


def _safe(fn, rc):
    try:
        return fn(rc)
    except Exception:            # noqa: BLE001 — a version probe must never break the report
        return None


# -- version comparison ---------------------------------------------------------------------------
# Best-effort across versioning schemes (a distro version "1.2.3-2" vs an upstream tag "v1.4.7"):
# osversion.parse_loose strips a Debian epoch + leading `v` and takes each token's leading digits.
# Where a string won't parse, the method abstains from tip/min (shown as-is, not wrongly ranked).

_pv = parse_loose


def _ge(a, b):
    pa, pb = _pv(a), _pv(b)
    return None if (pa is None or pb is None) else pa >= pb


def _lt(a, b):
    pa, pb = _pv(a), _pv(b)
    return False if (pa is None or pb is None) else pa < pb


def _max_version(versions):
    best, bestp = None, None
    for v in versions:
        p = _pv(v)
        if p is not None and (bestp is None or p > bestp):
            best, bestp = v, p
    return best


def report(ctx, name, *, min_version=None, refresh=False, now=None):
    '''Build the per-method VersionReport for `name` in this machine's context. Raises ResolveError
    if the component is unknown here.'''
    r = ctx.routes
    comp = r.components.get(name)
    if comp is None:
        raise ResolveError(f'unknown component "{name}"')
    cx = r.cascade.context(r.block, r.version, r.cpu)
    # enumerate ALL when:-valid methods (pins=None) — the whole point is to see the alternatives
    # you could pin to; the pin/default are marked per method below.
    cands = candidate_bindings(comp, r.cascade, cx, None)
    try:
        default_binding = select_binding(comp, r.cascade, cx, r.pins, r.preference, r.candidate_only)
    except ResolveError:
        default_binding = None                    # undecidable/none-here: no default marker
    pin = r.pins.get(name)

    cache = _LatestCache.load(ctx.paths)
    now = time.time() if now is None else now
    methods = []
    for b in cands:
        unit = unit_for_binding(comp, b, r.cascade, r.block, r.overrides)
        if unit is None:                          # parts aggregator / component-names drop
            continue
        rc = to_resolved_component(unit)
        drv = get_driver(rc.driver, ctx.runner, ctx.paths)
        methods.append(MethodVersion(
            via=b.via, driver=rc.driver, package=rc.name or comp.name,
            latest=_cached_latest(cache, rc, drv, refresh, now),
            installed=_safe(drv.get_version, rc) if drv is not None else None,
            is_default=(b is default_binding), is_pinned=(pin == b.via)))
    cache.save(ctx.paths)

    tip = _max_version([m.latest for m in methods])
    for m in methods:
        m.lags_tip = _lt(m.latest, tip)
        if min_version is not None:
            m.meets_min = _ge(m.latest, min_version)
    default_meets = next((m.meets_min for m in methods if m.is_default), None)
    return VersionReport(name=name, methods=methods, tip=tip, min_version=min_version,
                         default_meets_min=default_meets)
