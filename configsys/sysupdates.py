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

from .drivers import get_driver

# The cross-distro app managers we aggregate alongside the OS's native pm. P0 proves the pipeline on
# apt + flatpak + snap; P3 extends upgradable_index/upgrade_all to the rest (dnf/pacman/zypper/…).
_APP_MANAGERS = ('flatpak', 'snap')


class UpdateRow:
    '''One upgradable package in the System Updates lane — the manager's own report, not a component.'''
    __slots__ = ('manager', 'key', 'installed', 'candidate', 'held')

    def __init__(self, manager, key, installed, candidate, held):
        self.manager = manager
        self.key = key
        self.installed = installed
        self.candidate = candidate
        self.held = held


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
    '''{(driver_name, index_key)} for this machine's tracked (picked) components — the set the update
    lane EXCLUDES, so a managed pick shows in its own pick row, not here. Resolution only (no install
    inspection), so it's cheap. A native-backed driver's unit (aur / native-pkg-file / clang) is also
    keyed under the native pm, where its package actually lands.'''
    keys = set()
    native = _native_pm(ctx)
    try:
        units, _errs = ctx.routes.resolve_resilient(list(ctx.config.requested()))
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
        rows = []
        for key in sorted(idx):
            dedup = drv.update_dedup_key(key)          # apt/snap: == key; flatpak: the app id
            if (drv.name, dedup) in managed:
                continue
            inst, cand = idx[key]
            rows.append(UpdateRow(drv.name, key, inst, cand, dedup in held or key in held))
        if rows:
            out[drv.name] = rows
    return out
