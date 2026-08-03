'''flooradvise — the floor-aware advisory (stage 3: surface-and-choose).

Given the resolved plan for THIS machine, find every ACTIVE versioned requirement whose provider's
DEFAULT install method can't meet the floor, and advise how to fix it — pin the provider to a method
that does. Read-only: it NEVER swaps a method silently (the locked posture); it only surfaces the
choice. Reuses versionreport (real per-method versions) + versionsweep.providers_of, and is a no-op
when no floors are active, so it costs nothing until floors exist.
'''

from .resolve import cap_names
from .versionsweep import meets, providers_of


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


def advise(ctx, units):
    '''[{level, tag, text}] — one advisory per (requiring unit, unmet floor). Surfaced through
    ctx.diagnostics (inspect / the TUI ! page). Only fires when the provider's default method is
    DEFINITELY below the floor (an unknown/unparseable provider version abstains — no false alarm).'''
    from . import versionreport
    r = ctx.routes
    out, seen = [], set()
    reports = {}

    def rep(name):
        if name not in reports:
            try:
                reports[name] = versionreport.report(ctx, name)   # per-method versions; no --min
            except Exception:  # noqa: BLE001 — an unroutable provider just yields no advisory
                reports[name] = None
        return reports[name]

    for rc in units:
        comp = r.components.get(rc.comp)
        if comp is None:
            continue
        for cap, floor in active_floors(rc, comp).items():
            for provider in providers_of(r.components, cap):
                rp = rep(provider)
                if rp is None:
                    continue
                default = next((m for m in rp.methods if m.is_default), None)
                if default is None or default.latest is None:
                    continue                              # can't verify the default -> no alarm
                if meets(default.latest, floor):
                    continue                              # the default method meets the floor
                who = [m.via for m in rp.methods if m.latest and meets(m.latest, floor)]
                verb = 'meets' if len(who) == 1 else 'meet'
                fix = (f'pin {provider} to {who[0]} ({", ".join(who)} {verb} it): '
                       f'`configsys pin set {provider} {who[0]}`') if who else \
                      f'no install method here meets {cap} {floor}'
                # method-replacement is explicit, never automatic: if the too-old provider is
                # already INSTALLED via the default method, switching won't remove that install.
                replace = (f'  ({provider} is installed via {default.via}; switching won\'t remove '
                           f'it — remove it after)') if default.installed else ''
                text = (f'{rc.comp} (via {rc.via}) needs {cap} {floor}, but the default method for '
                        f'{provider} provides {default.latest}; {fix}{replace}')
                if text not in seen:
                    seen.add(text)
                    out.append({'level': 'warn', 'tag': 'floor', 'text': text})
    return out
