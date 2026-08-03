'''versionsweep — check authored version FLOORS against reality (sibling to the name sweep).

Two checks over the loaded routes for a machine context:
  * STRANDED requirement — a component declares `requires: { cap: ">=F" }` but no available method
    of any provider of `cap` reaches F here, so the floor can't be met (a real gap).
  * DISHONEST provides   — a binding/component declares `provides: { cap: ">=F" }` but the version
    the method actually delivers is BELOW F (a stale claim, e.g. after an upstream regression).

The CORE is pure: it takes the loaded components/drivers plus two injected version lookups, so it's
unit-testable without a network. The CLI (`sweep_ctx`) wires the lookups to real per-method versions
via versionreport (each method's get_latest), so a run reflects THIS machine's repos/discovery.
Networked + slow -> a maintenance tool, not part of pytest — like the name sweep.
'''

import re

from . import osversion

_EPOCH = re.compile(r'^\d+:')   # a Debian epoch, e.g. `2:1.18~0ubuntu2` -> `1.18~0ubuntu2`


def _pv(v):
    '''parse_version, normalizing for cross-scheme best-effort compare: strip a Debian epoch
    (`2:1.18…` would otherwise read as 2.18, spuriously beating a 1.x floor) and a leading `v`
    (git tags). parse_version then takes the leading numeric run of each dotted token, so a
    packaging suffix like `~0ubuntu2` is dropped.'''
    if v is None:
        return None
    s = _EPOCH.sub('', str(v).strip())
    if s[:1] in ('v', 'V') and s[1:2].isdigit():
        s = s[1:]
    return osversion.parse_version(s)


def meets(version, constraint):
    '''Does `version` satisfy `constraint` (`>=1.96`, `>1.0`, `=2.0`, `,`-AND ranges)? False when
    either is unparseable — an unverifiable floor is treated as NOT met (surfaced, not assumed ok).'''
    pv = _pv(version)
    clauses = osversion.parse_constraint(constraint)
    if pv is None or not clauses:
        return False
    return all(osversion._CMP[op or '='](pv, target) for op, target in clauses)


def collect_requirement_floors(components, drivers=None):
    '''[(component, level, cap, constraint)] for every versioned `requires:` — component-level,
    per-binding, and (driver-level constraints aren't authored today, so drivers is accepted but
    unused for now).'''
    out = []
    for name, comp in components.items():
        for cap, con in getattr(comp, 'req_versions', {}).items():
            out.append((name, 'component', cap, con))
        for b in comp.bindings:
            for cap, con in getattr(b, 'req_versions', {}).items():
                out.append((name, f'via {b.via}', cap, con))
    return out


def collect_provides_floors(components):
    '''[(component, where, cap, floor)] for every declared provided-version floor — component-level
    and per-binding (the version a method GUARANTEES).'''
    out = []
    for name, comp in components.items():
        for cap, floor in getattr(comp, 'prov_versions', {}).items():
            out.append((name, 'component', cap, floor))
        for b in comp.bindings:
            for cap, floor in getattr(b, 'prov_versions', {}).items():
                out.append((name, f'via {b.via}', cap, floor))
    return out


def providers_of(components, cap):
    '''Component names that provide `cap` (a component always provides its own name).'''
    return [n for n, c in components.items() if cap == n or cap in c.provides]


def sweep(components, drivers, best_version, method_version):
    '''Pure core. `best_version(cap) -> highest available version across any provider of cap, or
    None`. `method_version(component, where) -> the version that component's binding delivers, or
    None` (where is 'component' or 'via <x>'). Returns a list of finding dicts.'''
    findings = []
    for name, level, cap, con in collect_requirement_floors(components, drivers):
        best = best_version(cap)
        if not meets(best, con):
            findings.append({'kind': 'stranded', 'component': name, 'level': level,
                             'cap': cap, 'need': con, 'best': best})
    for name, where, cap, floor in collect_provides_floors(components):
        real = method_version(name, where)
        if real is not None and not meets(real, floor):   # None = can't verify -> abstain
            findings.append({'kind': 'dishonest', 'component': name, 'where': where,
                             'cap': cap, 'claimed': floor, 'real': real})
    return findings


def format_finding(f):
    if f['kind'] == 'stranded':
        best = f['best'] or 'none available'
        return (f"STRANDED  {f['component']} ({f['level']}) requires {f['cap']} {f['need']}, "
                f"but the best method here provides {best}")
    return (f"DISHONEST {f['component']} ({f['where']}) claims to provide {f['cap']} "
            f"{f['claimed']}, but actually delivers {f['real']}")


def sweep_ctx(ctx):
    '''Wire the pure core to real per-method versions via versionreport (each method's get_latest).
    Returns the findings list. Caches a report per component so shared providers aren't re-queried.'''
    from . import versionreport
    r = ctx.routes
    reports = {}

    def rep(nm):
        if nm not in reports:
            try:
                reports[nm] = versionreport.report(ctx, nm)
            except Exception:  # noqa: BLE001 — an unroutable provider just yields "unknown"
                reports[nm] = None
        return reports[nm]

    def best_version(cap):
        best, bestp = None, None
        for p in providers_of(r.components, cap):
            rp = rep(p)
            pv = _pv(rp.tip) if (rp and rp.tip) else None
            if pv is not None and (bestp is None or pv > bestp):
                best, bestp = rp.tip, pv
        return best

    def method_version(name, where):
        rp = rep(name)
        if rp is None:
            return None
        if where == 'component':                          # any method's best, for a component floor
            return rp.tip
        via = where[4:] if where.startswith('via ') else where
        m = next((m for m in rp.methods if m.via == via), None)
        return m.latest if m else None

    return sweep(r.components, r.drivers, best_version, method_version)
