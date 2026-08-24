'''flooradvise — the floor-aware advisory (stage 3: surface-and-choose).

Given the resolved plan for THIS machine, find every ACTIVE versioned requirement whose provider's
DEFAULT install method can't meet the floor, and advise how to fix it — pin the provider to a method
that does. Read-only: it NEVER swaps a method silently (the locked posture); it only surfaces the
choice. Reuses versionreport (real per-method versions) + versionsweep.providers_of, and is a no-op
when no floors are active, so it costs nothing until floors exist.
'''

import re

from .resolve import cap_names
from .versionsweep import _pv, meets, providers_of


def _declared_version(comp, cap):
    '''The CONCRETE version `comp` declares it provides for `cap` (component- or binding-level
    `provides: {cap: N}`), or None when it provides `cap` unversioned / by name. This is a
    version-scoped provider's fixed identity — what a constraint selects it BY.'''
    v = getattr(comp, 'prov_versions', {}).get(cap)
    if v is None:
        for b in comp.bindings:
            v = getattr(b, 'prov_versions', {}).get(cap)
            if v is not None:
                break
    return v if (v is not None and _pv(str(v)) is not None) else None


def active_floors(rc, comp):
    '''The versioned requirements ACTIVE for this resolved unit: component-level floors, plus the
    floors on the binding that actually WON (matched by via) — only for caps the unit really
    requires. A floor on a binding that didn't win, or for an un-required cap, is not active.'''
    floors = {cap: con for cap, con in comp.req_versions.items() if cap in comp.requires}
    b = next((b for b in comp.bindings if b.via == (rc.via or None)), None)
    if b is not None:
        reqs = set(cap_names(b.details.get('requires')))
        floors.update({cap: con for cap, con in b.req_versions.items() if cap in reqs})
    return floors


def _unmet(ctx, units):
    '''Yield (rc, cap, floor, provider, report, default_method) for each ACTIVE floor whose
    provider's DEFAULT method is DEFINITELY below the floor. Shared by advise + tighten_pins. An
    unknown/unparseable provider version abstains (no yield) — never a false positive.'''
    from . import versionreport
    r = ctx.routes
    reports = {}

    def rep(name):
        if name not in reports:
            try:
                reports[name] = versionreport.report(ctx, name)   # per-method versions
            except Exception:  # noqa: BLE001 — an unroutable provider just yields nothing
                reports[name] = None
        return reports[name]

    for rc in units:
        comp = r.components.get(rc.comp)
        if comp is None:
            continue
        for cap, floor in active_floors(rc, comp).items():
            for provider in providers_of(r.components, cap):
                pc = r.components.get(provider)
                # version-scoped providers: a provider whose FIXED declared version the floor excludes
                # is not the one the resolver picks for this constraint (a `<12` require selects
                # cuda-toolkit-11, never -12) — so its default method being "too old" is irrelevant.
                declared = _declared_version(pc, cap) if pc else None
                if declared is not None and not meets(str(declared), floor):
                    continue
                rp = rep(provider)
                if rp is None:
                    continue
                default = next((m for m in rp.methods if m.is_default), None)
                if default is None or default.latest is None:
                    continue                              # can't verify the default -> no alarm
                if meets(default.latest, floor):
                    continue                              # the default method meets the floor
                yield rc, cap, floor, provider, rp, default


def _provides_meets(comp, via, cap, floor):
    '''True when the binding for `via` DECLARES it provides a `cap` version satisfying `floor` —
    a static guarantee that stands in for a discovered `latest` when the method has no version
    source (e.g. the ghcup `via: script` binding promising `provides: { haskell: ">=9.4" }`). A
    lower-bound promise `>=X` meets a floor `>=Y` iff X itself meets the floor; a concrete `N` uses N.'''
    if comp is None:
        return False
    b = next((b for b in comp.bindings if b.via == via), None)
    if b is None:
        return False
    g = getattr(b, 'prov_versions', {}).get(cap)
    if g is None:
        return False
    m = re.search(r'[0-9][0-9.]*', str(g))            # the version literal inside `>=9.4` or `9.4`
    return m is not None and meets(m.group(0), floor)


def _who_meets(comp, rp, cap, floor):
    return [m.via for m in rp.methods
            if (m.latest and meets(m.latest, floor)) or _provides_meets(comp, m.via, cap, floor)]


def advise(ctx, units):
    '''[{level, tag, text}] — one advisory per (requiring unit, unmet floor). Surfaced through
    ctx.diagnostics (inspect / the TUI ! page).'''
    out, seen = [], set()
    for rc, cap, floor, provider, rp, default in _unmet(ctx, units):
        who = _who_meets(ctx.routes.components.get(provider), rp, cap, floor)
        verb = 'meets' if len(who) == 1 else 'meet'
        fix = (f'pin {provider} to {who[0]} ({", ".join(who)} {verb} it): '
               f'`configsys pin set {provider} {who[0]}`') if who else \
              f'no install method here meets {cap} {floor}'
        # method-replacement is explicit, never automatic: if the too-old provider is already
        # INSTALLED via the default method, switching won't remove that install.
        replace = (f'  ({provider} is installed via {default.via}; switching won\'t remove '
                   f'it — remove it after)') if default.installed else ''
        text = (f'{rc.comp} (via {rc.via}) needs {cap} {floor}, but the default method for '
                f'{provider} provides {default.latest}; {fix}{replace}')
        if text not in seen:
            seen.add(text)
            out.append({'level': 'warn', 'tag': 'floor', 'text': text})
    return out


def tighten_pins(ctx, units):
    '''{provider: via} to AUTO-select under opt-in `auto-tighten`: a floor-satisfying method for a
    provider whose default can't meet the floor — but ONLY when the provider isn't already
    INSTALLED via the default method (replacement stays explicit; those remain advisories). The
    monotonic-tighten step: it only ever moves a provider to a HIGHER-versioned method.'''
    pins = {}
    for _rc, cap, floor, provider, rp, default in _unmet(ctx, units):
        if default.installed:                             # a replacement -> never auto
            continue
        who = _who_meets(ctx.routes.components.get(provider), rp, cap, floor)
        if who and provider not in pins:
            pins[provider] = who[0]
    return pins


# -- resident floors: an INSTALLED toolchain that's too old for a consumer -----
# The advisories above ask "can a METHOD produce a version >= the floor?". This half asks the other
# question the method check misses: "is the toolchain that's ALREADY INSTALLED (and being reused via
# adopt-installed) new enough?" — e.g. a resident go 1.18 for a consumer that needs go >= 1.21, or a
# resident uv too old for pipx. It probes the resident version from the live states.

def resident_unmet(ctx, units, states):
    '''Yield (rc, cap, floor, provider_key, provider_state) for each ACTIVE floor whose RESIDENT
    provider (present in `states`) has a KNOWN version below the floor. Abstains on an unknown/
    unparseable version (never a false positive). `states` is {unit_key: ComponentState}.'''
    r = ctx.routes
    present = [(k, st) for k, st in (states or {}).items()
               if st.present and _pv(str(st.installed_version or '')) is not None]
    for rc in units:
        comp = r.components.get(rc.comp)
        if comp is None:
            continue
        for cap, floor in active_floors(rc, comp).items():
            provs = set(providers_of(r.components, cap))
            # Candidate residents = installed providers this constraint could actually SELECT. A
            # version-scoped provider whose FIXED declared version the floor EXCLUDES (a `<12` require
            # never selects cuda-toolkit-12) is not a candidate — skip it, exactly as the method-based
            # check does; otherwise a resident -12 falsely trips the floor for a `<12` consumer even
            # though the selected -11 is installed and fine (and "upgrade -12" would only worsen it).
            cands = []
            for pkey, pst in present:
                if pst.component.comp not in provs:
                    continue
                declared = _declared_version(r.components.get(pst.component.comp), cap)
                if declared is not None and not meets(str(declared), floor):
                    continue
                cands.append((pkey, pst))
            if not cands:
                continue
            if any(meets(str(pst.installed_version), floor) for _k, pst in cands):
                continue                                  # an installed provider already satisfies the floor
            yield rc, cap, floor, cands[0][0], cands[0][1]   # none do -> flag one offender


def resident_advise(ctx, units, states):
    '''[{level, tag, text}] — advisory for each consumer whose resident toolchain is below its floor,
    pointing at the exact `configsys upgrade <provider>` to run. Surfaced through ctx.diagnostics.'''
    out, seen = [], set()
    for rc, cap, floor, pkey, pst in resident_unmet(ctx, units, states):
        prov = pst.component.comp
        text = (f'{rc.comp} needs {cap} {floor}, but the installed {prov} is '
                f'{pst.installed_version} — run `configsys upgrade {prov}` '
                f'(or set `auto-tighten` to upgrade it automatically before installing {rc.comp})')
        if text not in seen:
            seen.add(text)
            out.append({'level': 'warn', 'tag': 'floor', 'text': text})
    return out


def resident_upgrades(ctx, units, states):
    '''{provider_key: provider_state} — resident providers to UPGRADE (under opt-in `auto-tighten`)
    because a consumer being installed floors them above their installed version. The caller inserts
    an `upgrade` op for each; dependency ordering already places a provider before its consumer.'''
    ups = {}
    for _rc, _cap, _floor, pkey, pst in resident_unmet(ctx, units, states):
        ups.setdefault(pkey, pst)
    return ups


def resident_upgrades_probed(ctx, units):
    '''{provider_key: provider_rc} to upgrade for the INSTALL path, where full states aren't loaded:
    probes each FLOORED provider's installed version on demand (only the providers a floor names, so
    it's cheap) and returns the resident ones below their floor. `units` is {unit_key: rc}.'''
    from .drivers import get_driver
    r = ctx.routes
    by_comp = {}                                          # comp name -> (unit_key, rc), first wins
    for k, rc in units.items():
        by_comp.setdefault(rc.comp, (k, rc))
    ups, probed = {}, {}
    for rc in units.values():
        comp = r.components.get(rc.comp)
        if comp is None:
            continue
        for cap, floor in active_floors(rc, comp).items():
            for prov in providers_of(r.components, cap):
                hit = by_comp.get(prov)
                if hit is None or hit[0] in ups:
                    continue
                # a version-scoped provider the floor EXCLUDES isn't this constraint's provider — never
                # "upgrade" it toward an upper bound (a `<12` require won't be helped by bumping -12).
                declared = _declared_version(r.components.get(prov), cap)
                if declared is not None and not meets(str(declared), floor):
                    continue
                pkey, prc = hit
                if pkey not in probed:
                    drv = get_driver(prc.driver, ctx.runner, ctx.paths)
                    try:
                        probed[pkey] = drv.get_version(prc) if drv is not None else None
                    except Exception:                     # noqa: BLE001 — an unprobeable provider abstains
                        probed[pkey] = None
                iv = probed[pkey]
                if iv is None or _pv(str(iv)) is None or meets(str(iv), floor):
                    continue                              # absent/unknown/already-adequate -> skip
                ups[pkey] = prc
    return ups
