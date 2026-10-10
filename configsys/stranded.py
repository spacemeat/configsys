'''stranded.py — installs routes no longer offer here, and picks with no install method left.

Routes change under an installed machine: an AUR package is promoted to pacman (its AUR binding is
deleted), an AppImage is dropped or gated to a newer glibc, a download gains a cpu gate, the user
disables a driver. The install is still on disk — but every detection pass (inspect, the detection
tier, detect_coexisting, the method-switch swap) walks only the component's CURRENT candidate
bindings, so it went invisible: the component read "not installed", and installing it again doubled
up (librewolf-bin vs librewolf). This module finds those installs and classifies a component's
routing state, shown as a status distinct from `outdated`:

  switch   — installed via a method that isn't a candidate here any more (removed from routes,
             gated out, or its driver disabled) while another valid method exists. NOT staged
             automatically (no surprises): the TUI shows the status, `v` repins, and the existing
             method-switch swap (installState.plan_with_swaps) removes the stranded install.
  unmet    — no install method enabled, but one would be valid if a `disabled-drivers:` driver
             were on (directly, or somewhere in its requires-closure). Not dangling.
  dangling — no install method valid on this OS at all. Never staged for removal: an existing
             install keeps working, and removing it is the user's call.

Where a stranded install is found, in order:
  1. receipts — the ledger's record of the units configsys installed (exact; survives the binding's
     removal, and carries the fields the driver needs to remove it).
  2. bindings not valid here — a `when:`/cpu-gated or disabled-driver binding still in routes.
     `native` bindings are skipped: a gated native binding describes ANOTHER OS's package and would
     only map onto this OS's manager by accident.
  3. the AUR heuristic — a foreign pacman package (`pacman -Qm`) named <comp> or <comp>-<variant>
     (-bin/-git/-appimage/…) with no receipt: AUR installs from before receipts existed, whose
     binding has since been removed.
'''

from dataclasses import dataclass, field

from .componentObj import ResolvedComponent
from .drivers import get_driver

ROUTE_STATUSES = ('dangling', 'unmet', 'switch')        # precedence, most severe first
NO_METHOD = '—'                  # driver of a placeholder row: a pick with no install method here

# config drivers link files, they aren't an install METHOD of a component
_SKIP_VIAS = frozenset({'native', 'parts', 'dotfiles', 'glue'})

# AUR packaging-variant suffixes: `<comp>-<variant>` is the same software. A bare `<comp>-*` would
# misfire on unrelated packages (`go` vs `go-task-bin`, `bat` vs `bat-extras`).
AUR_VARIANTS = ('bin', 'git', 'appimage', 'nightly', 'beta', 'stable', 'latest', 'hg', 'svn',
                'release', 'prebuilt')

REASON_TEXT = {
    'removed': 'routes no longer offer that method',
    'gated': 'that method is no longer valid on this machine',
    'disabled': 'that driver is disabled here (disabled-drivers:)',
}


@dataclass(frozen=True)
class Stranded:
    rc: ResolvedComponent = field(hash=False, compare=False)
    key: str
    version: str
    reason: str                    # 'removed' | 'gated' | 'disabled'

    @property
    def via(self):
        return self.rc.via or self.rc.driver

    def describe(self):
        return f'{self.via} ({self.rc.name} {self.version})'


def _rc_from_receipt(key, rec, comp):
    driver = key.split('\\', 1)[0]
    fields = dict(rec.get('fields') or {})
    fields['name'] = rec['name']
    return ResolvedComponent(key=key, driver=driver, comp=comp, via=rec.get('via') or driver,
                             fields=fields, requested_as={comp})


def _unit_rc(r, comp, b):
    from .adapt import to_resolved_component
    from .resolve import unit_for_binding
    try:
        unit = unit_for_binding(comp, b, r.cascade, r.block, r.overrides)
    except Exception:                                   # noqa: BLE001 — an odd binding finds nothing
        return None
    return to_resolved_component(unit) if unit is not None else None


def _os_db(ctx, driver_name):
    '''True when `driver_name` installs into the OS package database (a native manager, or a
    native-backed driver).'''
    from .drivers._native import NativePkgManager
    drv = get_driver(driver_name, ctx.runner, ctx.paths)
    return drv is not None and (isinstance(drv, NativePkgManager) or getattr(drv, 'native_backed', False))


def _probe(ctx, cache, rc):
    drv = get_driver(rc.driver, ctx.runner, ctx.paths)
    if drv is None:
        return None
    try:
        return cache.version(drv, rc) if cache is not None else drv.get_version(rc)
    except Exception:                                   # noqa: BLE001
        return None


def find(ctx, comp_name, *, ledger, cache=None, foreign=None):
    '''[Stranded] — installs of `comp_name` via a method that isn't one of its current candidates
    here. Empty in the common case. `foreign` = the AUR driver's foreign_index() (None off Arch).'''
    from .resolve import candidate_bindings
    r = ctx.routes
    comp = r.components.get(comp_name)
    disabled = getattr(r, 'disabled', frozenset())
    cand = candidate_bindings(comp, r.cascade, r.context()) if comp is not None else []
    cand_names = {}                                      # current method unit key -> package name
    for b in cand:
        rc = _unit_rc(r, comp, b)
        if rc is not None:
            cand_names[rc.key] = rc.name

    # package names a current method installs into the OS package database (apt/dnf/pacman/…, or a
    # native-backed driver: native-pkg-file / aur / gcc+clang PPAs). Another method naming the SAME
    # package in that same database IS that install — gh's EL-only .rpm binding probing dpkg on Pop
    # finds the apt gh — so it's never "stranded" (cf. a same-name AUR->[extra] promotion).
    native_pkgs = {nm for k, nm in cand_names.items() if _os_db(ctx, k.split('\\', 1)[0])}

    def is_current(rc):
        if cand_names.get(rc.key) == rc.name:
            return True
        return rc.name in native_pkgs and _os_db(ctx, rc.driver)

    found = {}
    # 1. receipts: exact, and the only source that survives the binding's removal
    for key, rec in sorted(ledger.receipts_for(comp_name).items()):
        rc = _rc_from_receipt(key, rec, comp_name)
        if is_current(rc):
            continue
        ver = _probe(ctx, cache, rc)
        if ver is None:
            continue                                     # stale receipt: nothing on disk
        # 'gated'/'disabled' only when a binding in routes still describes THIS package; a removed
        # binding, or one now naming a different package (antigravity-bin -> antigravity), is 'removed'
        same = [b for b in (comp.bindings if comp is not None else ())
                if (lambda u: u is not None and u.key == key and u.name == rc.name)(_unit_rc(r, comp, b))]
        if not same:
            reason = 'removed'
        elif any(b.via in disabled for b in same):
            reason = 'disabled'
        else:
            reason = 'gated'
        found[key] = Stranded(rc, key, ver, reason)
    # 2. bindings still in routes but not candidates here (gated by when:/cpu, or a disabled driver)
    if comp is not None:
        cand_ids = {id(b) for b in cand}
        for b in comp.bindings:
            if id(b) in cand_ids or b.via in _SKIP_VIAS:
                continue
            rc = _unit_rc(r, comp, b)
            if rc is None or rc.key in found or is_current(rc):
                continue
            ver = _probe(ctx, cache, rc)
            if ver is not None:
                found[rc.key] = Stranded(rc, rc.key, ver, 'disabled' if b.via in disabled else 'gated')
    # 3. the AUR heuristic — only for installs no receipt explains
    if foreign:
        key = f'aur\\{comp_name}'
        names = [comp_name] + [f'{comp_name}-{v}' for v in AUR_VARIANTS]
        known = {s.rc.name for s in found.values()} | set(cand_names.values())
        hit = next((n for n in names if n in foreign and n not in known), None)
        if hit and key not in found and cand_names.get(key) != hit:
            rc = ResolvedComponent(key=key, driver='aur', comp=comp_name, via='aur',
                                   fields={'name': hit}, requested_as={comp_name})
            # a package a CURRENT native binding names (same-name promotion) isn't stranded: pacman
            # reads it as installed natively and `pacman -Syu` replaces the foreign build itself
            if not any(rk.startswith('pacman\\') and nm == hit for rk, nm in cand_names.items()):
                found[key] = Stranded(rc, key, foreign[hit], 'removed')
    return sorted(found.values(), key=lambda s: s.key)


def foreign_index(ctx, cache=None):
    '''The AUR driver's foreign-package map, or None off Arch (cheap: one `pacman -Qm`, cached).'''
    import shutil
    if not shutil.which('pacman'):
        return None
    drv = get_driver('aur', ctx.runner, ctx.paths)
    fn = getattr(drv, 'foreign_index', None)
    if fn is None:
        return None
    holder = getattr(cache, '_cfs_foreign', None) if cache is not None else None
    if holder is not None:
        return holder[0]
    try:
        idx = fn()
    except Exception:                                    # noqa: BLE001
        idx = None
    if cache is not None:
        cache._cfs_foreign = (idx,)
    return idx


def classify_unroutable(ctx, names):
    '''{name: (status, detail)} for requested `names` that failed to resolve because no install
    method is valid ('dangling') or only a disabled driver's would be ('unmet'). Names that failed
    for other reasons (ambiguity, an unknown component) are left out — they stay errors.'''
    from .resolve import candidate_bindings
    r = ctx.routes
    disabled = frozenset(getattr(r, 'disabled', ()) or ())
    out = {}
    for name in names:
        comp = r.components.get(name)
        if comp is None:
            continue
        if candidate_bindings(comp, r.cascade, r.context()):
            # it HAS a method; did a disabled driver break its requires-closure?
            if disabled and not _routes(r, name) and _routes_without_disabled(r, name):
                out[name] = ('unmet', 'a dependency needs a disabled driver ('
                             + ', '.join(sorted(disabled)) + ')')
            continue
        # nothing valid now; with no driver disabled, is there? Then disabling is the cause — either
        # the method's own driver is disabled, or its driver's requires need one (snap on Arch needs
        # snapd, which only installs via aur: disable aur and snap can't work either)
        would = candidate_bindings(comp, r.cascade, r.context(disabled=())) if disabled else []
        if would:
            vias = sorted({b.via for b in would})
            direct = [v for v in vias if v in disabled]
            out[name] = ('unmet', f'only installable via disabled driver(s): {", ".join(direct)}' if direct
                         else f'only installable via {", ".join(vias)}, which needs a disabled driver '
                              f'({", ".join(sorted(disabled))})')
        else:
            out[name] = ('dangling', 'no install method on this OS any more')
    return out


def _routes(r, name):
    try:
        _units, errs = r.resolve_resilient([name])
        return name not in errs
    except Exception:                                    # noqa: BLE001
        return False


def _routes_without_disabled(r, name):
    saved = r.disabled
    try:
        r.disabled = frozenset()
        _units, errs = r.resolve_resilient([name])
        return name not in errs
    except Exception:                                    # noqa: BLE001
        return False
    finally:
        r.disabled = saved


def augment(ctx, states, ledger, cache=None):
    '''Mark resolved states whose component is ALSO installed via a stranded method: route_status
    'switch', `stranded`, and the stranded installs folded into `also_present` (so the TUI's
    method-swap offer after `v` sees them). Mutates and returns `states`.'''
    from .installState import _parallel_map
    r = ctx.routes
    foreign = foreign_index(ctx, cache)
    for st in states.values():                # a reload reuses states: drop the previous verdict
        if getattr(st, 'route_status', None) == 'switch':
            old = {(s.via, s.rc.name) for s in st.stranded}
            st.also_present = tuple(a for a in st.also_present if (a[0], a[1]) not in old)
            st.route_status, st.stranded = None, ()
    by_comp = {}
    for st in states.values():
        rc = st.component
        if rc.driver in ('glue', 'dotfiles') or rc.comp not in r.components:
            continue
        by_comp.setdefault(rc.comp, []).append(st)

    def _one(item):
        name, sts = item
        return name, sts, find(ctx, name, ledger=ledger, cache=cache, foreign=foreign)

    for _name, sts, found in _parallel_map(_one, list(by_comp.items())):
        if not found:
            continue
        for st in sts:
            st.stranded = tuple(found)
            st.route_status = 'switch'
            have = {(v, p) for v, p, _ in st.also_present}
            st.also_present = tuple(st.also_present) + tuple(
                (s.via, s.rc.name, s.version) for s in found if (s.via, s.rc.name) not in have)
    return states


def unroutable_states(ctx, classes, ledger, cache=None):
    '''{key: ComponentState} rows for picks classified dangling/unmet (classify_unroutable), so they
    show in the Components view with their status instead of vanishing into an error. A row whose
    component is still installed (via a stranded method) carries that install — present, removable.'''
    from .installState import ComponentState
    foreign = foreign_index(ctx, cache)
    out = {}
    for name, (status, detail) in sorted(classes.items()):
        found = find(ctx, name, ledger=ledger, cache=cache, foreign=foreign)
        if found:
            s = found[0]
            rc = ResolvedComponent(key=s.key, driver=s.rc.driver, comp=name, via=s.rc.via,
                                   fields=dict(s.rc.fields), requested_as={name})
            present, ver = True, s.version
        else:
            rc = ResolvedComponent(key=f'{NO_METHOD}\\{name}', driver=NO_METHOD, comp=name,
                                   requested_as={name})
            present, ver = False, None
        out[rc.key] = ComponentState(
            component=rc, supported=True, present=present, installed_version=ver,
            latest_version=None, locked=False, lock_source=None, managed=False, error=None,
            route_status=status, route_detail=detail, stranded=tuple(found))
    return out


def stranded_reasons(st):
    '''{(via, package): reason} for a state's stranded installs — to label them where `also_present`
    is shown (they can't be adopted with a pin: routes don't offer that method here).'''
    return {(s.via, s.rc.name): s.reason for s in getattr(st, 'stranded', ()) or ()}


def diagnostics(states):
    '''[(level, tag, text)] — one line per component with a route status, for the ! page / inspect.'''
    out, seen = [], set()
    for st in states.values():
        status = getattr(st, 'route_status', None)
        name = st.component.comp
        if not status or (name, status) in seen:
            continue
        seen.add((name, status))
        installs = ', '.join(s.describe() for s in st.stranded)
        if status == 'switch':
            why = '; '.join(sorted({REASON_TEXT[s.reason] for s in st.stranded}))
            out.append(('warn', 'switch',
                        f'{name}: installed via {installs} — {why}. Installing it (TUI `i`, or '
                        f'`configsys install {name}`) swaps that out for {st.component.driver}; '
                        f'`v` first to choose a different method'))
        elif status == 'unmet':
            out.append(('warn', 'unmet', f'{name}: {st.route_detail}'
                        + (f' — still installed via {installs}' if installs else '')))
        else:
            out.append(('warn', 'dangling', f'{name}: {st.route_detail}'
                        + (f' — still installed via {installs}; left in place (remove it yourself '
                           f'if you no longer want it)' if installs else '')))
    return out
