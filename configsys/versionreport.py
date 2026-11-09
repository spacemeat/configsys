'''versionreport.py — per-install-method version visibility.

For a component, report what version EACH candidate install method (native / tarball / source /
flatpak / …) would install here, mark the default and any installed method, and flag methods that
lag the newest available ("tip"). Read-only substrate shared by `configsys versions`
(cli.where.cmd_versions), the TUI install-method picker (`v`, tui.flows._pick_method_name), the
version-floor advisory (flooradvise) and the version sweep (versionsweep), the last two through the
per-pass `Reports` memo.

It reuses each driver's `get_latest` ("what would this method install"). Native `get_latest`
queries the box's package manager and is slow, so latest results are cached machine-locally with a
TTL (`state_dir/method-versions.hu`); `refresh=True` bypasses. Installed versions (`get_version` /
the installed index) are read through the context's shared ProbeCache (probecache.py) — current
right after an install/remove, because a reload drops what the ops it ran touched.
'''

import time

from . import probecache
from dataclasses import dataclass, field

from .adapt import to_resolved_component
from .drivers import get_driver
from .osversion import parse_loose
from .resolve import ResolveError, candidate_bindings, unit_for_binding
from .cachefile import TTLRecords

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
    note: str = None             # optional one-line advisory (e.g. pipx: python caps the version)


@dataclass
class VersionReport:
    name: str
    methods: list = field(default_factory=list)
    tip: str = None              # newest available across methods
    min_version: str = None
    default_meets_min: bool = None   # does the DEFAULT method clear the floor?


# -- machine-local cache of get_latest results (keyed by `driver\comp\package`) -----------------

class _LatestCache(TTLRecords):
    '''method-versions.hu — each install method's get_latest, keyed by _cache_key (cachefile).'''
    path_attr = 'method_versions_file'

    def set(self, key, version, now):
        self.records[key] = {'version': version, 'fetched': now}
        self.dirty = True


def _cache_key(rc):
    '''One slot per (unit, PACKAGE): two bindings of one component can resolve to the same driver
    with different `name:`s (p7zip's `p7zip-full` and `7zip` on apt) — one unit key, two answers.'''
    return f'{rc.key}\\{rc.name}'


def _cached_latest(cache, rc, drv, refresh, now):
    '''get_latest for a method, via the machine-local cache. A cache miss/expiry queries the driver
    (guarded — a probe failure is just "unknown", never fatal). "Unknown" (None/empty) is NEVER
    cached, and a cached EMPTY is treated as a miss — so a method whose driver only later learns to
    report a version (e.g. flatpak gaining get_latest) self-heals on the next read instead of being
    stuck on a stale blank until the TTL expires.'''
    if not refresh:
        hit = cache.get(_cache_key(rc), now, LATEST_TTL)
        if hit and hit['version']:
            return hit['version']
    ver = _safe(drv.get_latest, rc) if drv is not None else None
    if ver:                          # only cache a real answer; retry "unknown" next time
        cache.set(_cache_key(rc), ver, now)
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


def max_version(versions):
    '''The newest of `versions` (strings, cross-scheme) — the first of equals; unparseable / None
    entries abstain. None when none parses.'''
    best, bestp = None, None
    for v in versions:
        p = _pv(v)
        if p is not None and (bestp is None or p > bestp):
            best, bestp = v, p
    return best


_max_version = max_version


class Reports:
    '''A per-pass memo of report(ctx, name): call it with a component name; an unroutable one is None
    (never raises). The floor advisory and the version sweep ask about each provider once.'''
    def __init__(self, ctx):
        self.ctx, self._got = ctx, {}

    def __call__(self, name):
        if name not in self._got:
            try:
                self._got[name] = report(self.ctx, name)
            except Exception:    # noqa: BLE001 — an unroutable provider just yields "unknown"
                self._got[name] = None
        return self._got[name]


def report(ctx, name, *, min_version=None, refresh=False, now=None):
    '''Build the per-method VersionReport for `name` in this machine's context. Raises ResolveError
    if the component is unknown here.'''
    r = ctx.routes
    comp = r.components.get(name)
    if comp is None:
        raise ResolveError(f'unknown component "{name}"')
    cx = r.context()
    # enumerate ALL when:-valid methods (pins=None) — the whole point is to see the alternatives
    # you could pin to; the pin/default are marked per method below.
    cands = candidate_bindings(comp, r.cascade, cx, None)
    try:
        default_binding = r.select(comp, context=cx).binding
    except ResolveError:
        default_binding = None                    # undecidable/none-here: no default marker
    pin = r.pins.get(name)

    probes = probecache.of(ctx)
    cache = _LatestCache.load(ctx.paths)
    now = time.time() if now is None else now
    methods, seen = [], {}
    for b in cands:
        unit = unit_for_binding(comp, b, r.cascade, r.block, r.overrides)
        if unit is None:                          # parts aggregator / component-names drop
            continue
        rc = to_resolved_component(unit)
        package = rc.name or comp.name
        dup = seen.get((rc.driver, package))
        if dup is not None:                       # two bindings, one (driver, package): one row
            dup.is_default = dup.is_default or b is default_binding
            dup.is_pinned = dup.is_pinned or pin == b.via
            continue
        drv = get_driver(rc.driver, ctx.runner, ctx.paths)
        adv = getattr(drv, 'version_advisory', None) if drv is not None else None
        latest = _cached_latest(cache, rc, drv, refresh, now)
        note = _safe(adv, rc) if adv is not None else None
        if note is None and drv is not None and rc.fields.get('upstream'):
            up = _safe(drv.upstream_version, rc)          # a recipe-pinned method behind upstream
            if up and _lt(latest, up):
                from .installState import recipe_pin_text
                note = recipe_pin_text(latest, up)
        methods.append(MethodVersion(
            via=b.via, driver=rc.driver, package=package,
            latest=latest,
            # installed: through the context's shared probe cache (the detection passes filled it) —
            # the floor advisory reports per provider on every TUI diagnostics pass
            installed=_safe(lambda u, d=drv: probes.version(d, u), rc) if drv is not None else None,
            is_default=(b is default_binding), is_pinned=(pin == b.via),
            note=note))
        seen[(rc.driver, package)] = methods[-1]
    if not getattr(ctx.runner, 'pretend', False):      # pretend probes read empty: never cache that
        cache.save(ctx.paths)

    tip = max_version([m.latest for m in methods])
    for m in methods:
        m.lags_tip = _lt(m.latest, tip)
        if min_version is not None:
            m.meets_min = _ge(m.latest, min_version)
    default_meets = next((m.meets_min for m in methods if m.is_default), None)
    return VersionReport(name=name, methods=methods, tip=tip, min_version=min_version,
                         default_meets_min=default_meets)
