'''orphans.py — find installed things configsys COULD manage but that aren't in your active profiles.

The complement of the detection tier: detection asks "what's installed that I should ADOPT as the
method for a component I'm resolving?"; this asks "what's installed that NO active profile accounts
for at all?" — so the user can adopt it into a profile, remove it, or dismiss it.

An orphan has two orthogonal fields (see docs/managed-orphans-plan.md):
  * kind   — WHAT it is, one of KINDS, chosen by a priority ladder (most-actionable first):
               excluded  — installed, but an active profile `~`-removed it (you said "not here").
               lurking   — installed, has a recipe, lives in some profile, but none active selects it.
               forgotten — installed, has a recipe, but sits in no profile at all.
               foreign   — installed, but NO cf recipe matches the key (user-facing drivers only).
  * ignored — a STATUS overlay (the `orphans-ignore:` list), orthogonal to kind; an ignored orphan
              keeps its kind, it's just filtered out of the default surfaces.

Cost: one batched `installed_index()` per enumerable package-manager driver (shareable with the
detection cache) + pure set/graph math. No network, no per-item subprocess.
'''

from dataclasses import dataclass
from fnmatch import fnmatch

from .adapt import to_resolved_component
from .drivers import get_driver
from .resolve import candidate_bindings, unit_for_binding

# Drivers whose FOREIGN (no-recipe) installs we still list — deliberate user-app installs, few in
# number. Native package managers and language module installers are NOT here: they carry hundreds of
# dependency packages, so for them we only ever list the KNOWN intersection (a matched recipe).
USER_FACING = ('flatpak', 'snap')

# priority ladder: index 0 is the most actionable, chosen first when a key maps to several kinds.
KINDS = ('excluded', 'lurking', 'forgotten', 'foreign')

# OS-base priority tiers (apt Priority): the "the distro ships this" set, hidden from the foreign
# list by default. The tier is still recorded on the orphan — a user CAN opt to manage one.
BASE_TIERS = ('required', 'important', 'standard')


@dataclass
class Orphan:
    driver: str
    key: str                       # the installed_index key (package name / app id)
    version: str                   # installed version (or '' if the lister didn't report one)
    component: str                 # mapped component name, or '' for a foreign orphan
    kind: str                      # one of KINDS
    ignored: bool = False
    tier: str = ''                 # OS-origin tier (apt Priority), '' when the driver has no notion


def build_reverse_index(ctx):
    '''{ (driver, package_key): [component_name, ...] } for THIS machine's context — every package
    key each component could install under, across ALL its valid bindings (per-driver `name:` maps
    applied, and every same-`via:` alternative, so both `p7zip-full` and `7zip` map to one
    component). This is what tells a `known` key (maps to a real component) from a `foreign` one.'''
    r = ctx.routes
    cx = r.cascade.context(r.block, r.version, r.cpu)
    native_mgr = _native_manager(ctx)
    index = {}
    for name, comp in r.components.items():
        try:
            cands = candidate_bindings(comp, r.cascade, cx, None)   # ALL valid bindings, not one/via
        except Exception:                       # noqa: BLE001 — an unroutable component maps nothing
            continue
        for b in cands:
            unit = unit_for_binding(comp, b, r.cascade, r.block, r.overrides)
            if unit is None:
                continue
            rc = to_resolved_component(unit)
            drv = get_driver(rc.driver, ctx.runner, ctx.paths)
            if drv is None:
                continue
            for (dn, key) in _index_pairs(rc, drv, native_mgr):
                index.setdefault((dn, key), [])
                if name not in index[(dn, key)]:
                    index[(dn, key)].append(name)
    return index


def _native_manager(ctx):
    '''The OS's native package-manager driver name (apt/dnf/pacman/…), or None — where a
    native-backed driver's packages actually get enumerated.'''
    r = ctx.routes
    try:
        return r.cascade.native(r.block)
    except Exception:                           # noqa: BLE001
        return None


def _unit_keys(rc, drv):
    '''The installed_index key(s) a resolved unit occupies under its OWN driver: its `index_key`,
    plus any extra package names a unit installs (`fields['packages']` — an apt metapackage, or a
    clang-N unit whose `packages: [ clang-18 ]` are the real dpkg names).'''
    keys = {drv.index_key(rc)}
    for extra in (rc.fields.get('packages') or []):
        keys.add(extra)
    return keys


def _index_pairs(rc, drv, native_mgr):
    '''All (driver, key) slots a resolved unit occupies in the installed indexes: its own driver's
    keys, plus — for a native-backed driver (clang/gcc/native-pkg-file/aur) — the same keys under
    the native manager, where enumeration actually finds them (dpkg lists `clang-18`, not the `clang`
    driver).'''
    keys = _unit_keys(rc, drv)
    pairs = {(rc.driver, k) for k in keys}
    if native_mgr and getattr(drv, 'native_backed', False):
        pairs |= {(native_mgr, k) for k in keys}
    return pairs


def _classify_known(cfg, name, requested, active_profiles, removed_by_active):
    '''The kind of a KNOWN orphan (maps to component `name`), or None if it's not actually an orphan
    (the active config wants it — net-active, member-wins). Priority: excluded > lurking > forgotten.'''
    if name in requested:                       # an active profile asks for it -> managed, not orphan
        return None
    if name in removed_by_active:               # an active profile `~`-removed it -> excluded
        return 'excluded'
    try:
        direct, indirect = cfg.profiles_containing(name)
    except Exception:                           # noqa: BLE001 — a broken profile graph -> treat as none
        direct, indirect = [], []
    if direct or indirect:                      # in SOME profile, just none active -> lurking
        return 'lurking'
    return 'forgotten'                          # in no profile at all


def _rank(kind):
    return KINDS.index(kind)


def scan_orphans(ctx, units, *, cache=None, explicit=None, origins=None,
                 include_foreign_native=False, include_auto=False, include_system=False):
    '''[Orphan] — installed items with no active component. `units` is the active resolved set
    ({key: ResolvedComponent}). `cache` is an optional {driver_name: installed_index()-dict|None} to
    reuse detection's enumeration (missing drivers are enumerated on demand); `explicit` likewise
    caches {driver_name: explicit_keys()-set|None}. `include_foreign_native` opts native package
    managers into foreign listing (off by default — dependency noise). `include_auto` keeps
    auto-installed dependency packages (by default the scan lists only what the user EXPLICITLY
    installed, per each driver's explicit_keys — so the thousands of dep packages nobody chose
    don't drown the signal).'''
    cfg = ctx.config
    cache = dict(cache or {})
    explicit = dict(explicit or {})
    origins = dict(origins or {})
    drivers = {}                                # name -> Driver instance (memoized)

    def _drv(dname):
        if dname not in drivers:
            drivers[dname] = get_driver(dname, ctx.runner, ctx.paths)
        return drivers[dname]

    def _index(dname):
        if dname not in cache:
            drv = _drv(dname)
            try:
                cache[dname] = drv.installed_index() if drv is not None else None
            except Exception:                   # noqa: BLE001 — a flaky lister -> treat as unknowable
                cache[dname] = None
        return cache[dname]

    def _explicit(dname):
        '''The user-installed key set for a driver (None = it draws no manual/auto distinction, so
        everything counts as explicit). Bypassed entirely under include_auto.'''
        if include_auto:
            return None
        if dname not in explicit:
            drv = _drv(dname)
            try:
                explicit[dname] = drv.explicit_keys() if drv is not None else None
            except Exception:                   # noqa: BLE001 — a flaky query -> don't filter
                explicit[dname] = None
        return explicit[dname]

    def _tier(dname, key):
        '''The OS-origin tier for an installed key (apt Priority), '' when unknown. Falls back to the
        bare name for an arch-qualified key (dpkg reports priority per package, not per arch).'''
        if dname not in origins:
            drv = _drv(dname)
            try:
                origins[dname] = (drv.origin_index() if drv is not None else None) or {}
            except Exception:                   # noqa: BLE001 — a flaky query -> no tiers
                origins[dname] = {}
        idx = origins[dname]
        return idx.get(key) or idx.get(key.split(':')[0], '')

    # 1. the (driver, key) set we DO manage on this machine — the active resolved units. Native-backed
    # units (clang-N, a .deb, an aur pkg) also occupy a slot under the native manager, so subtract
    # those too — else an active clang-18 would resurface as an apt orphan.
    native_mgr = _native_manager(ctx)
    active = set()
    for rc in units.values():
        drv = _drv(rc.driver)
        if drv is None:
            continue
        active |= _index_pairs(rc, drv, native_mgr)

    # 2. classification inputs from the config's profile graph.
    rindex = build_reverse_index(ctx)
    requested = set(cfg.requested())            # components any ACTIVE profile asks for (post-`~`)
    active_profiles = list(cfg.active_profiles)
    removed_by_active = set()
    for p in active_profiles:
        try:                                    # closure: catches a `~` buried in an included subprofile
            removed_by_active |= set(cfg.profile_removed_closure(p))
        except Exception:                       # noqa: BLE001 — a broken active profile removes nothing
            pass
    ignore = _ignore_globs(cfg)

    # 3. walk every enumerable driver's installed set, subtract what we manage, classify the rest.
    scan_drivers = ({rc.driver for rc in units.values()} | {d for (d, _k) in rindex}
                    | set(USER_FACING))
    out = []
    for dname in sorted(scan_drivers):
        idx = _index(dname)
        if not idx:                             # None (not enumerable) or empty -> nothing to scan
            continue
        user_facing = dname in USER_FACING
        manual = _explicit(dname)               # None -> no manual/auto distinction; list all
        for key, version in idx.items():
            if (dname, key) in active:
                continue                        # managed by an active unit
            if manual is not None and key not in manual:
                continue                        # an auto-installed dependency, not a chosen package
            comps = rindex.get((dname, key))
            if comps:                           # KNOWN — pick the most-actionable kind across matches
                best = None
                for name in comps:
                    kind = _classify_known(cfg, name, requested, active_profiles, removed_by_active)
                    if kind is not None and (best is None or _rank(kind) < _rank(best[1])):
                        best = (name, kind)
                if best is None:
                    continue                    # every match is actively wanted -> not an orphan
                comp, kind = best
            elif user_facing:                   # unmatched key on a user-facing driver -> foreign
                comp, kind = '', 'foreign'
            elif include_foreign_native:
                comp, kind = '', 'foreign'
            else:
                continue                        # unmatched native key -> dependency noise, dropped
            tier = _tier(dname, key)
            if kind == 'foreign' and not include_system and tier in BASE_TIERS:
                continue                        # an OS-base package (required/important/standard)
            out.append(Orphan(driver=dname, key=key, version=version or '', component=comp,
                              kind=kind, ignored=_is_ignored(ignore, comp, key), tier=tier))
    out.sort(key=lambda o: (_rank(o.kind), o.driver, o.component or o.key))
    return out


def _ignore_globs(cfg):
    getter = getattr(cfg, 'orphans_ignore', None)
    try:
        return list(getter()) if callable(getter) else []
    except Exception:                           # noqa: BLE001
        return []


def _is_ignored(globs, comp, key):
    '''An orphan is ignored when a glob matches its component name OR its installed key.'''
    return any(fnmatch(comp, g) or fnmatch(key, g) for g in globs)


def scanned_summary(orphans):
    '''(known_count, foreign_count, ignored_count) over a scan result — for the report footer.'''
    known = sum(1 for o in orphans if o.kind != 'foreign' and not o.ignored)
    foreign = sum(1 for o in orphans if o.kind == 'foreign' and not o.ignored)
    ignored = sum(1 for o in orphans if o.ignored)
    return known, foreign, ignored
