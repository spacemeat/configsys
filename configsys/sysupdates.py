'''sysupdates.py — the System Updates lane (spec: docs/system-updates.md; history: docs/done/system-update-coverage-plan.md).

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

# The cross-distro app managers we aggregate alongside the OS's native pm. Every native manager
# (apt/dnf/pacman/zypper/apk/xbps/brew) implements upgradable_index/upgrade_all; rpm-ostree is omitted.
_APP_MANAGERS = ('flatpak', 'snap')

# TUI (P2): the synthetic Components group (its subgroups are the UPDATE_TIERS themselves).
SYSTEM_UPDATES_GROUP = 'System Updates'


class UpdateRow:
    '''One upgradable package in the System Updates lane — the manager's own report, not a component.'''
    __slots__ = ('manager', 'key', 'installed', 'candidate', 'held', 'tier', 'explicit', 'scope')

    def __init__(self, manager, key, installed, candidate, held, tier='apps', explicit=True,
                 scope='system'):
        self.manager = manager
        self.key = key
        self.installed = installed
        self.candidate = candidate
        self.held = held
        self.tier = tier
        self.explicit = explicit         # user-installed (manager's explicit set) vs auto-pulled dep
        self.scope = scope               # the installation it lives in (flatpak: --user or --system)


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
    '''{(driver_name, package_key)} for every package ANY component could install here — the set the
    update lane EXCLUDES, so anything cfs knows as a component is handled in the component/orphan
    world, not double-listed. Built from orphans.build_reverse_index, so it is METHOD-COMPLETE: it
    covers every valid binding of every component (a chrome installed as a flatpak is excluded via its
    flatpak binding even though its DEFAULT route is the vendor .deb), the per-driver `name:` maps,
    apt `packages:` sets (python3.10 + -minimal + -venv + -dev), and native-backed cross-indexing
    (clang/aur/native-pkg-file under the native pm). SU only lists upgradable (installed) packages, so
    covering not-installed component keys too is harmless. Empty on any failure — never bricks the lane.'''
    try:
        from . import orphans
        return set(orphans.build_reverse_index(ctx))
    except Exception:                                    # noqa: BLE001 — never let this brick `updates`
        return set()


def gather(ctx, notes_out=None):
    '''{manager_name: [UpdateRow]} of upgradable − managed, per manager present on this machine. A
    manager that can't enumerate (absent / query failed) or reports nothing upgradable is omitted.
    `notes_out` (a list) collects each manager's `upgradable_advisory()` — the optional hook a driver
    exposes when its list may be incomplete (pacman without checkupdates reads a stale sync DB) —
    as "<manager>: <why>", even when that manager listed nothing. The OS's OWN manager answering
    None is certainly installed, so its query failed: that is a note too, never a silent "no
    updates" (an app manager answering None is simply absent).'''
    managed = managed_keys(ctx)
    native = _native_pm(ctx)
    out = {}
    for drv in machine_managers(ctx):
        idx = drv.upgradable_index()
        adv = getattr(drv, 'upgradable_advisory', None)
        note = adv() if callable(adv) else None
        if note and notes_out is not None:
            notes_out.append(f'{drv.name}: {note}')
        if idx is None and drv.name == native and notes_out is not None:
            notes_out.append(f'{drv.name}: could not list upgradable packages')
        if not idx:                                      # None (absent/failed) or {} (up to date)
            continue
        scopes = getattr(drv, 'update_scopes', None) or {}   # flatpak: which installation each ref is in
        held = drv.held_keys() or set()
        tiers = drv.classify_index(list(idx))          # {key: UPDATE_TIER}
        explicit = drv.explicit_keys()                 # user-installed set (None = manager has no notion)
        rows = []
        for key in sorted(idx):
            dedup = drv.update_dedup_key(key)          # apt/snap: == key; flatpak: the app id
            if (drv.name, dedup) in managed:
                continue
            inst, cand = idx[key]
            # explicit_keys is bare names; None -> the manager draws no auto/manual distinction (treat
            # all as user-chosen, so nothing is dimmed).
            is_explicit = True if explicit is None else (dedup in explicit or key in explicit)
            rows.append(UpdateRow(drv.name, key, inst, cand, dedup in held or key in held,
                                  tiers.get(key, 'apps'), is_explicit, scopes.get(key, 'system')))
        if rows:
            out[drv.name] = rows
    return out


_SCAN_LOCK = threading.Lock()     # orders a scan's result store against invalidate()


# -- TUI: a background scan + the synthetic Components tree injection (P2) -----

def start_scan(ctx):
    '''Run gather() on a daemon thread and cache it on ctx._sysupd_groups, so the ~3.5s of manager
    queries never blocks TUI startup — the System Updates group folds into the Components tree once
    ready (the run loop polls scan_busy/take_dirty). No-op if a result is already cached or a scan of
    the CURRENT generation is in flight. A scan started before the last invalidate() is superseded:
    a fresh one starts, and the stale thread's result is discarded when it lands (see invalidate).
    Under --pretend nothing is scanned (the runner would echo every query over the curses screen, and
    a dry run reads nothing anyway): the group is simply empty. A gather that raises leaves a
    `scan failed` note for the `!` page instead of reading as "no updates".'''
    if getattr(ctx, '_sysupd_groups', None) is not None:
        return
    if getattr(getattr(ctx, 'runner', None), 'pretend', False):
        ctx._sysupd_groups = {}
        return
    gen = getattr(ctx, '_sysupd_gen', 0)
    t = getattr(ctx, '_sysupd_thread', None)
    if t is not None and t.is_alive() and getattr(ctx, '_sysupd_thread_gen', 0) == gen:
        return
    ctx._sysupd_dirty = False

    def run():
        notes = []
        try:
            g = gather(ctx, notes)
        except Exception as e:                           # noqa: BLE001 — never let the scan brick the TUI
            g, notes = {}, [f'system-updates: scan failed: {e}']
        with _SCAN_LOCK:                                 # atomic vs invalidate()'s bump + clear
            if getattr(ctx, '_sysupd_gen', 0) != gen:
                return                                   # superseded by an invalidate(): drop it
            ctx._sysupd_notes = notes                    # the `!` page lists them (Context._diagnostics)
            ctx._sysupd_groups = g
            ctx._sysupd_dirty = True

    ctx._sysupd_thread_gen = gen
    ctx._sysupd_thread = threading.Thread(target=run, daemon=True)
    ctx._sysupd_thread.start()


def scan_busy(ctx):
    '''True while the background gather of the current generation is running (its result not yet
    folded). A superseded scan still finishing in the background doesn't count.'''
    t = getattr(ctx, '_sysupd_thread', None)
    return bool(t is not None and t.is_alive()
                and getattr(ctx, '_sysupd_thread_gen', 0) == getattr(ctx, '_sysupd_gen', 0))


def take_dirty(ctx):
    '''True once when a fresh scan result has arrived and not yet been folded (clears the flag).'''
    if getattr(ctx, '_sysupd_dirty', False):
        ctx._sysupd_dirty = False
        return True
    return False


def invalidate(ctx):
    '''Drop the cached scan so the next start_scan re-gathers — after a system upgrade or refresh.
    Bumps the scan GENERATION, so a scan still in flight (started before the upgrade/refresh) can't
    land its stale result afterwards, and start_scan won't mistake it for the fresh one.'''
    with _SCAN_LOCK:
        ctx._sysupd_gen = getattr(ctx, '_sysupd_gen', 0) + 1
        ctx._sysupd_groups = None
        ctx._sysupd_notes = []
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


def apply_bulk(ctx, manager_names, *, refresh=True, on_start=None, on_line=print):
    '''Run each named manager's own bulk upgrade (Driver.upgrade_all) — the ONE System Updates apply
    step `upgrade --system` and the TUI execute path share. Refreshes the native index once up front
    so candidates are current (`refresh=False` when the caller already refreshed for the whole
    batch), then drops the cached scan (invalidate); rescanning is the caller's (the TUI re-gathers
    after its component ops, the CLI exits).
    Returns an actions.RunResult like run_plan's: one OpOutcome per manager, keyed
    `system-updates\\<mgr>` (a manager with no bulk-upgrade command is an advisory outcome, not a
    failure), the failure records — already folded into the ! page / `report` record, except under
    --pretend — and interrupted=True (rc 130, the remaining managers skipped) after a ^C.'''
    from . import reportgen
    from .actions import OpOutcome, RunResult, fail_detail
    if refresh:
        from .cli.refresh import refresh_native_index             # lazy: the cli layer imports this module
        refresh_native_index(ctx)                         # non-fatal
    outcomes, failures, n_fatal, exit_code, interrupted = [], [], 0, 0, False
    for mgr in manager_names:
        key = f'system-updates\\{mgr}'
        if on_start is not None:
            on_start(mgr)                                 # (the CLI prints a header per manager)
        drv = get_driver(mgr, ctx.runner, ctx.paths)
        try:
            res = drv.upgrade_all() if drv is not None else None
        except KeyboardInterrupt:                         # like run_plan: ^C stops the whole batch
            on_line(f'\n  ^C — aborted; the {mgr} upgrade may be partially applied. Skipping the rest.')
            outcomes.append(OpOutcome('upgrade', key, mgr, False, 'interrupted (^C)'))
            exit_code, interrupted = 130, True
            break
        if res is None:
            on_line(f'  ({mgr} has no bulk-upgrade command — skipped)')
            outcomes.append(OpOutcome('upgrade', key, mgr, False, 'no bulk-upgrade command',
                                      advisory=True))
        elif not res.ok:
            on_line(f'  -> {mgr} upgrade FAILED (exit {res.returncode}): {fail_detail(res)}')
            outcomes.append(OpOutcome('upgrade', key, mgr, False, fail_detail(res)))
            failures.append(reportgen.failure_from_result(key, mgr, 'upgrade', res))
            exit_code = exit_code or res.returncode or 1
            n_fatal += 1
        else:
            outcomes.append(OpOutcome('upgrade', key, mgr, True))
    if not getattr(ctx.runner, 'pretend', False):         # the ! page + `report` see a failure
        reportgen.record_run(ctx.paths, failures, [o.key for o in outcomes])
    invalidate(ctx)
    return RunResult(outcomes, failures, n_fatal, exit_code, interrupted)


def _synthetic_state(row):
    '''One display-only ComponentState wrapping an UpdateRow: present + always-outdated (so it reads
    as upgradable), a `system_update` flag that keeps it out of staging/execution, and a key that
    can't collide with a real unit key.'''
    from .componentObj import ResolvedComponent
    from .installState import ComponentState
    token = row.tier if row.tier in UPDATE_TIERS else 'apps'
    scope = row.scope
    # su_auto flags an auto-pulled dependency (not in the manager's user-installed set) — the painter
    # dims those in the standard/apps tiers so the handful you actually chose stand out.
    rc = ResolvedComponent(
        key=f'sysupd\\{row.manager}\\{row.key}', driver=row.manager, comp=row.key,
        fields={'name': row.key, 'system_update': True, 'su_auto': not row.explicit,
                'su_tier': row.tier}, requested_as={token})
    return ComponentState(
        component=rc, supported=True, present=True,
        installed_version=row.installed, latest_version=row.candidate,
        locked=row.held, lock_source=('native' if row.held else None),
        error=None, scope=scope, outdated_override=True)


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
            items.append(('component', tier))
            transitive_names.append(tier)
    if not items:
        return {}, [], {}
    return states, [(SYSTEM_UPDATES_GROUP, items)], {SYSTEM_UPDATES_GROUP: transitive_names}
