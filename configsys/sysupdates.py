'''sysupdates.py — the System Updates lane (docs/system-update-coverage-plan.md, P0).

cfs's normal pipeline tracks a machine's PICKS. Everything else the OS reports upgradable — base
packages, dependencies, flatpak runtimes, snaps — is invisible, so the user still reaches for
Pop!_Shop / `apt upgrade`. This module surfaces that "upgradable − managed" set from each manager's
OWN upgradable list (NOT modeled as routes.hu components — no binding, no version-lock) and drives
each manager's bulk upgrade.

Load-bearing reframe (grilled 2026-09-21): cfs does NOT model base-vs-dep. It asks each manager
"what's upgradable?" (Driver.upgradable_index) and runs the manager's own bulk upgrade
(Driver.upgrade_all). Within-release only — never a release jump.
'''

import threading

from .driver import UPDATE_TIERS
from .drivers import get_driver

# The cross-distro app managers we aggregate alongside the OS's native pm. P0 proves the pipeline on
# apt + flatpak + snap; P3 extends upgradable_index/upgrade_all to the rest (dnf/pacman/zypper/…).
_APP_MANAGERS = ('flatpak', 'snap')

# TUI (P2): the synthetic Components group + its per-tier subgroup labels.
SYSTEM_UPDATES_GROUP = 'System Updates'
_TIER_TOKEN = {'kernel': 'kernel', 'core': 'core', 'standard': 'standard', 'apps': 'apps'}


class UpdateRow:
    '''One upgradable package in the System Updates lane — the manager's own report, not a component.'''
    __slots__ = ('manager', 'key', 'installed', 'candidate', 'held', 'tier')

    def __init__(self, manager, key, installed, candidate, held, tier='apps'):
        self.manager = manager
        self.key = key
        self.installed = installed
        self.candidate = candidate
        self.held = held
        self.tier = tier


def _native_pm(ctx):
    try:
        return ctx.routes.cascade.native(ctx.os_info.block)
    except Exception:                                    # noqa: BLE001 — a bare test stub
        return None


def machine_managers(ctx):
    '''The manager drivers to consult on THIS machine: the OS's native pm + the app managers, each
    instantiated once. Availability is decided lazily — a manager that isn't installed answers None
    from upgradable_index() and the caller drops it — so no probe is needed here.'''
    names, seen, out = [], set(), []
    native = _native_pm(ctx)
    if native:
        names.append(native)
    names.extend(_APP_MANAGERS)
    for n in names:
        if n in seen:
            continue
        seen.add(n)
        drv = get_driver(n, ctx.runner, ctx.paths)
        if drv is not None:
            out.append(drv)
    return out


def managed_keys(ctx):
    '''{(driver_name, index_key)} for everything cfs KNOWS as a component and has installed — the set
    the update lane EXCLUDES, so anything with a recipe (a pick OR an installed-but-untracked orphan
    like wget/tor) is handled in the component/orphan world, not double-listed here. System Updates is
    then the genuinely-unmanaged tail (base/deps/runtimes cfs has no recipe for); the bulk `apt
    upgrade` still patches the excluded ones anyway. Resolution + one install scan; a native-backed
    driver's unit (aur / native-pkg-file / clang) is also keyed under the native pm where it lands.'''
    keys = set()
    native = _native_pm(ctx)
    names = set(ctx.config.requested())                  # picks
    try:
        units0, _e = ctx.routes.resolve_resilient(list(names))
        from . import orphans
        installed, _orph, _c = orphans.install_overlay(ctx, units0)
        names |= (installed & set(ctx.routes.components))   # + installed things cfs has a recipe for
    except Exception:                                    # noqa: BLE001 — fall back to picks-only exclusion
        pass
    try:
        units, _errs = ctx.routes.resolve_resilient(list(names))
        ctx.prepare_units(units)
    except Exception:                                    # noqa: BLE001 — never let this brick `updates`
        return keys
    for rc in units.values():
        drv = get_driver(rc.driver, ctx.runner, ctx.paths)
        if drv is None:
            continue
        k = drv.index_key(rc)
        keys.add((rc.driver, k))
        if getattr(drv, 'native_backed', False) and native:
            keys.add((native, k))
    return keys


def gather(ctx):
    '''{manager_name: [UpdateRow]} of upgradable − managed, per manager present on this machine. A
    manager that can't enumerate (absent / query failed) or reports nothing upgradable is omitted.'''
    managed = managed_keys(ctx)
    out = {}
    for drv in machine_managers(ctx):
        idx = drv.upgradable_index()
        if not idx:                                      # None (absent/failed) or {} (up to date)
            continue
        held = drv.held_keys() or set()
        tiers = drv.classify_index(list(idx))          # {key: UPDATE_TIER}
        rows = []
        for key in sorted(idx):
            dedup = drv.update_dedup_key(key)          # apt/snap: == key; flatpak: the app id
            if (drv.name, dedup) in managed:
                continue
            inst, cand = idx[key]
            rows.append(UpdateRow(drv.name, key, inst, cand, dedup in held or key in held,
                                  tiers.get(key, 'apps')))
        if rows:
            out[drv.name] = rows
    return out


# -- TUI: a background scan + the synthetic Components tree injection (P2) -----

def start_scan(ctx):
    '''Run gather() on a daemon thread and cache it on ctx._sysupd_groups, so the ~3.5s of manager
    queries never blocks TUI startup — the System Updates group folds into the Components tree once
    ready (the run loop polls scan_busy/take_dirty). No-op if a result is already cached or a scan is
    in flight.'''
    if getattr(ctx, '_sysupd_groups', None) is not None:
        return
    t = getattr(ctx, '_sysupd_thread', None)
    if t is not None and t.is_alive():
        return
    ctx._sysupd_dirty = False

    def run():
        try:
            g = gather(ctx)
        except Exception:                                # noqa: BLE001 — never let the scan brick the TUI
            g = {}
        ctx._sysupd_groups = g
        ctx._sysupd_dirty = True

    ctx._sysupd_thread = threading.Thread(target=run, daemon=True)
    ctx._sysupd_thread.start()


def scan_busy(ctx):
    '''True while the background gather is running (its result not yet folded).'''
    t = getattr(ctx, '_sysupd_thread', None)
    return bool(t is not None and t.is_alive())


def take_dirty(ctx):
    '''True once when a fresh scan result has arrived and not yet been folded (clears the flag).'''
    if getattr(ctx, '_sysupd_dirty', False):
        ctx._sysupd_dirty = False
        return True
    return False


def invalidate(ctx):
    '''Drop the cached scan so the next start_scan re-gathers — after a system upgrade or refresh.'''
    ctx._sysupd_groups = None
    ctx._sysupd_dirty = False


def cached_total(ctx):
    '''The number of upgradable packages in the last scan (0 if none / not yet scanned) — the header
    count chip.'''
    groups = getattr(ctx, '_sysupd_groups', None)
    return sum(len(v) for v in groups.values()) if groups else 0


def is_synthetic(state):
    '''True for a synthetic System Updates row (fabricated for display; staged as a bulk mark, applied
    via apply_bulk — never routed through run_plan per-row).'''
    return bool(getattr(getattr(state, 'component', None), 'fields', {}).get('system_update'))


def apply_bulk(ctx, manager_names):
    '''Run each named manager's own bulk upgrade (Driver.upgrade_all) — the System Updates apply step
    the TUI execute path calls after the shared confirm. Refreshes the native index once up front so
    candidates are current, then invalidates the cache + restarts the scan so the group refreshes.
    Returns [(manager, Result_or_None)].'''
    from .app import refresh_native_index                 # lazy: app imports this module
    refresh_native_index(ctx)                             # non-fatal
    results = []
    for mgr in manager_names:
        drv = get_driver(mgr, ctx.runner, ctx.paths)
        results.append((mgr, drv.upgrade_all() if drv is not None else None))
    invalidate(ctx)
    start_scan(ctx)
    return results


def _synthetic_state(row):
    '''One display-only ComponentState wrapping an UpdateRow: present + always-outdated (so it reads
    as upgradable), a `system_update` flag that keeps it out of staging/execution, and a key that
    can't collide with a real unit key.'''
    from .componentObj import ResolvedComponent
    from .installState import ComponentState
    token = _TIER_TOKEN.get(row.tier, 'apps')
    scope = 'user' if row.manager == 'flatpak' else 'system'
    rc = ResolvedComponent(
        key=f'sysupd\\{row.manager}\\{row.key}', driver=row.manager, comp=row.key,
        fields={'name': row.key, 'system_update': True}, requested_as={token})
    return ComponentState(
        component=rc, supported=True, present=True,
        installed_version=row.installed, latest_version=row.candidate,
        locked=row.held, lock_source=('native' if row.held else None),
        managed=False, error=None, scope=scope, outdated_override=True)


def tree_injection(groups):
    '''Turn gathered groups into (states, layouts, transitive) for the Components tree: one
    `System Updates` PROFILE whose items are the non-empty tiers (kernel/core/standard/apps), each a
    COMPONENT group (its packages the UNIT leaves). Rows are keyed by tier TOKEN via requested_as, so
    _build_tree groups them without any special-casing. Returns ({}, [], {}) when there's nothing.'''
    if not groups:
        return {}, [], {}
    states, by_tier = {}, {t: [] for t in UPDATE_TIERS}
    for mgr in sorted(groups):
        for row in groups[mgr]:
            st = _synthetic_state(row)
            states[st.component.key] = st
            by_tier[row.tier if row.tier in by_tier else 'apps'].append(st)
    items, transitive_names = [], []
    for tier in UPDATE_TIERS:
        if by_tier[tier]:
            token = _TIER_TOKEN[tier]
            items.append(('component', token))
            transitive_names.append(token)
    if not items:
        return {}, [], {}
    return states, [(SYSTEM_UPDATES_GROUP, items)], {SYSTEM_UPDATES_GROUP: transitive_names}
