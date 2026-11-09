'''cli/where.py — `where`, `search`, `location`, `versions` — the explain/report verbs.

Split out of app.py (review-2026-11-2 D2).
'''

import sys
from ..errors import ConfigError
from ..drivers import get_driver


def _fmt_val(v):
    '''Compact one-line rendering of a binding detail value.'''
    if isinstance(v, dict):
        return '{' + ' '.join(f'{k}={_fmt_val(x)}' for k, x in v.items()) + '}'
    if isinstance(v, list):
        return '[' + ', '.join(_fmt_val(x) for x in v) + ']'
    s = str(v)
    return s if len(s) <= 60 else s[:57] + '...'


def _fmt_binding(b, selected, reachable=False, shadowed=False, invalid=None):
    when = b.when if b.when else 'always'
    details = '  '.join(f'{k}={_fmt_val(v)}' for k, v in b.details.items())
    if invalid:                         # not a candidate: resolve.not_candidate_reason says why
        mark = f'  (not a candidate: {invalid})'
    elif selected:
        mark = '  <- default here'
    elif shadowed:
        mark = f'  (shadowed — pinning via:{b.via} resolves a more-specific binding above)'
    elif reachable:
        mark = '  (alternative here — pin to use)'
    else:
        mark = ''
    return f'    - via {b.via}   when: {when}' + (f'   {details}' if details else '') + mark


def _layer_label(source, paths):
    '''A friendly label for a source file: 'routes.hu' for the repo routing base, else the
    path with $HOME collapsed to ~ (so user/included files show where they live).'''
    if source in (str(paths.routes_file), paths.routes_file):
        return 'routes.hu'
    from ..paths import tilde
    return tilde(source, paths.home)


def _source_label(comp, paths):
    '''Human provenance line for a component's definition.'''
    where = _layer_label(comp.source, paths)
    if where == 'routes.hu':
        return 'routes.hu'
    if not comp.bindings:
        return f'{where}   (removes routes.hu\'s definition)' if comp.shadows else \
               f'{where}   (defined empty / removed)'
    return f'{where}   (overrides routes.hu)' if comp.shadows else f'{where}   (new; not in routes.hu)'


def _os_version_conditions(comp, cx):
    '''The versioned OS atoms in `comp`'s `when:`s that name a block in this machine's lineage
    (`alpine >= 3.24`), as text — each reads false while no OS version is known.'''
    from .. import predicate
    found = []

    def walk(p):
        if isinstance(p, (predicate.And, predicate.Or)):
            for t in p.terms:
                walk(t)
        elif isinstance(p, predicate.Not):
            walk(p.term)
        elif isinstance(p, predicate.Os) and p.op is not None and p.name in cx.lineage:
            text = f'{p.name} {p.op} {".".join(map(str, p.version))}'
            if text not in found:
                found.append(text)

    for b in comp.bindings:
        if b.pred is not None:
            walk(b.pred)
    return found


def where_report(ctx, name):
    '''The `configsys where` report for `name` as a list of text lines — shared by the CLI
    (cmd_where prints them) and the TUI (`w` full-page overlay renders them). None if unknown.'''
    from ..resolve import (ResolveError, candidate_bindings, via_representatives,
                          not_candidate_reason)
    r = ctx.routes
    comp = r.components.get(name)
    if comp is None:
        return None

    def _fmt_caps(names, versions):
        # annotate a capability with its version floor when one is declared: `cargo (>=1.96)`
        return ', '.join(f'{n} ({versions[n]})' if n in versions else n for n in names)

    out = [name, f'  defined in  {_source_label(comp, ctx.paths)}']
    if comp.provides:
        out.append(f'  provides    {_fmt_caps(comp.provides, comp.prov_versions)}')
    if comp.requires:
        out.append(f'  requires    {_fmt_caps(comp.requires, comp.req_versions)}')
        # how each required capability's provider was decided, when a rule other than "the only
        # one" did it (e.g. `standing: 5`) — recorded by the last resilient resolve
        rules = getattr(r, 'provider_rules', None) or {}
        if not any(c in rules for c in comp.requires):     # no pipeline ran (CLI `where`): ask now
            _out = {}
            try:
                r.resolve_resilient([name], out=_out)
            except Exception:                              # noqa: BLE001 — an explanation never fails
                pass
            rules = _out.get('provider_rules') or {}
        decided = [f'{c} by {rules[c]}' for c in comp.requires
                   if c in rules and rules[c] != 'only provider here']
        if decided:
            out.append(f'  providers   {", ".join(decided)}')
    from ..resolve import binding_pin
    pinned = binding_pin(r.pins, name)
    if pinned is not None:
        out.append(f'  pinned      via:{pinned}   (from your config)')
    elif r.pins.get(name) is not None:              # a provider-pin on the capability this component names
        out.append(f'  provider    {name} -> {r.pins[name]}   (a provider-pin for what requires {name})')

    # which binding wins in this machine's context, plus the alternatives available here
    cx = r.context()
    selected, candidates, reason = None, [], None
    if comp.bindings:
        try:
            selected, candidates, reason = r.select(comp, context=cx)
        except ResolveError:
            candidates = candidate_bindings(comp, r.cascade, cx, r.pins)  # valid but none / undecidable
        reps = via_representatives(candidates, r.cascade)      # per-via winners — the pin-reachable set
        out.append('  bindings')
        for b in comp.bindings:
            valid = b in candidates
            out.append(_fmt_binding(b, b is selected, reachable=(b in reps and b is not selected),
                                    shadowed=(valid and b not in reps),
                                    invalid=None if valid else not_candidate_reason(
                                        b, r.cascade, cx, pin=pinned)))
        if selected is not None and len(candidates) > 1:
            out.append(f'    default: via {selected.via}  (by {reason})')

    # how it actually resolves on this machine
    ver = f' {r.version}' if r.version else ''
    out.append('')
    out.append(f'  on {r.block}{ver} ({r.cpu}):')
    if not r.version:
        conds = _os_version_conditions(comp, cx)
        if conds:
            out.append(f'    (no OS version set, so {", ".join(conds)} reads false here; ask about a '
                       f'release with --os {r.block}:VERSION)')
    if not comp.bindings:
        out.append('    nothing (removed)')
        return out
    try:
        units = r.resolve_names([name])
    except ResolveError as e:
        out.append(f'    ERROR: {e}')
        return out
    if not units:
        out.append('    nothing')
        return out
    own = {k for k in units if k.split('\\', 1)[-1] == name}
    for key in sorted(units):
        rc = units[key]
        tag = '' if key in own else '   (dep)'
        pkg = f'  pkg {rc.name}' if rc.name else ''
        out.append(f'    {key}{pkg}{tag}')
    return out


def where_profile_report(ctx, name):
    '''`configsys where -p <profile>` — provenance for a PROFILE: each layer's raw definition
    (low → high), the relation the top layer takes to lower same-name defs (tracked/shadowed/
    base), and the effective members/declined counts. None if the profile is unknown. Shared
    by the CLI and the TUI Profiles infobox.'''
    cfg = ctx.config
    defs = cfg.profile_layer_defs(name)
    if not defs and name not in cfg.profile_names():
        return None

    def label(src):
        if src in (str(ctx.paths.config_file), ctx.paths.config_file):
            return 'config.hu (repo)'
        from ..paths import tilde
        return tilde(src, ctx.paths.home)

    out = [name, f'  browse lens   relation: {cfg.profile_relation(name)}']
    out.append('  layers (low → high)')
    for d in defs:
        out.append(f'    {label(d["source"])}  [{d["role"]}]')
        out.append(f'      terms: [ {"  ".join(d["terms"])} ]' if d['terms'] else '      terms: []')
    try:
        members = sorted(cfg.profile_components(name))
    except ConfigError:
        members = []
    declined = sorted(cfg.profile_removed(name))
    out.append('')
    out.append(f'  members {len(members)}   declined {len(declined)}')
    if declined:
        out.append(f'    declined: {", ".join(declined)}')
    return out


def picks_snapshot(cfg):
    '''This machine's picks (`requested()`) as a set — taken before/after a plugin sync/update to
    report what it moved (a synced primary plugin can carry new or dropped picks).'''
    try:
        return set(cfg.requested())
    except Exception:                                  # noqa: BLE001 — a broken config snapshots empty
        return set()


def sync_delta(before, cfg):
    '''(added, removed) picks vs the `before` snapshot, both sorted.'''
    after = picks_snapshot(cfg)
    return sorted(after - before), sorted(before - after)


def delta_summary(before, cfg):
    '''print_sync_delta in one line, for a status bar (the TUI Plugins sync note — parity-17):
    "install set +2 / -1 (review on Components)", or '' when nothing moved.'''
    added, removed = sync_delta(before, cfg)
    if not (added or removed):
        return ''
    return f'install set +{len(added)} / -{len(removed)} (review on Components)'


def print_sync_delta(before, cfg):
    '''After a sync/update, print how this machine's picks moved vs the `before` snapshot (a synced
    primary's `picks:` changed upstream).'''
    added, removed = sync_delta(before, cfg)
    if added or removed:
        print("configsys: this machine's picks changed:")
        for c in added:
            print(f'  + {c}')
        for c in removed:
            print(f'  - {c}')
        print('  review with `configsys inspect`, then install/upgrade to apply')


def catalog_search(components, words=(), attrs=()):
    '''[(name, component)] matching every word (case-insensitive, in the name or description) and
    carrying every attr — the CLI's view of what the TUI browses with `/`, `F` and `f` (G6).'''
    words = [w.lower() for w in words]
    want = {a.lower() for a in attrs}
    out = []
    for name in sorted(components):
        comp = components[name]
        if not getattr(comp, 'bindings', None):
            continue                                   # a `{}`-removed component
        hay = f'{name} {getattr(comp, "description", "")}'.lower()
        if not all(w in hay for w in words):
            continue
        if want and not want <= {a.lower() for a in getattr(comp, 'attrs', ())}:
            continue
        out.append((name, comp))
    return out


def cmd_search(ctx, args):
    '''Search the catalog (G6 / parity-18).'''
    hits = catalog_search(ctx.routes.components, args.text, args.attr)
    picked = set(ctx.config.requested())
    if args.json:
        import json
        print(json.dumps([{'name': n, 'description': c.description, 'attrs': list(c.attrs),
                           'picked': n in picked} for n, c in hits], indent=2))
        return 0
    if not hits:
        print('configsys: no component matches')
        return 1
    width = min(28, max(len(n) for n, _c in hits))
    for n, c in hits:
        mark = '+' if n in picked else ' '
        print(f'{mark} {n:<{width}}  {c.description}' + (f'  [{" ".join(c.attrs)}]' if c.attrs else ''))
    print(f'\n{len(hits)} component(s){"; + = picked on this machine" if picked & {n for n, _c in hits} else ""}')
    return 0


def cmd_where(ctx, args):
    if getattr(args, 'profile', False):
        lines = where_profile_report(ctx, args.name)
        if lines is None:
            print(f'configsys: unknown profile "{args.name}"')
            return 1
        print('\n' + '\n'.join(lines))
        return 0
    lines = where_report(ctx, args.name)
    if lines is None:
        print(f'configsys: unknown component "{args.name}" '
              f'(not in routes.hu or your config)')
        return 1
    print('\n' + '\n'.join(lines))
    return 0


def cmd_location(ctx, args):
    '''Print the absolute install location of a component as it resolves HERE (honoring scope and
    the effective pin) — one path per line. For shell snippets: `export X="$(configsys location
    vulkan-sdk)/lib"` instead of hunting through candidate dirs. Exits non-zero (message on stderr)
    only if the component is UNROUTABLE / resolves to nothing; a resolved component whose driver
    manages no location (a native/PATH install) is a valid empty answer -> exit 0, empty stdout.'''
    from ..resolve import ResolveError
    r = ctx.routes
    if getattr(args, 'all', False):
        return _location_all(ctx)
    if not args.name:
        print('configsys: location needs a component name (or --all)', file=sys.stderr)
        return 1
    try:
        units = r.resolve_names([args.name])
    except ResolveError as e:
        print(f'configsys: {e}', file=sys.stderr)
        return 1
    ctx.prepare_units(units)                             # honor scope + `locations:` (else wrong dir)
    own = [rc for rc in units.values() if rc.comp == args.name]
    if not own:
        print(f'configsys: {args.name} resolves to nothing here', file=sys.stderr)
        return 1
    found = False
    for rc in own:
        drv = get_driver(rc.driver, ctx.runner, ctx.paths)
        if drv is None:
            continue
        # reflect the ACTUAL install scope (user vs system) when installed — get_installed probes
        # both — so the path matches reality, not just the configured target. Not installed ->
        # (None) -> the configured/default-scope target dir (where it WOULD land).
        try:
            _ver, detected = drv.get_installed(rc)
        except Exception:  # noqa: BLE001 - a probe failure must not break a location query
            detected = None
        if detected:
            rc.fields['scope'] = detected
        loc = drv.location(rc)
        if loc:
            s = str(loc)
            print(ctx.paths.expand(s) if s.startswith(('~', '/')) else s)   # absolute for scripts
            found = True
    if not found:
        # Resolved fine, but this driver manages no location (a native/PATH install) — that's a
        # valid EMPTY answer to the query, not an error. Exit 0 (message on stderr) so a shell
        # snippet can `var loc = (configsys location X 2>/dev/null | slurp)` without the nonzero
        # exit raising (elvish) or needing exit-swallowing. Genuine errors (unroutable / resolves
        # to nothing) still return 1 above.
        print(f'configsys: {args.name} ({own[0].driver}) has no managed install location '
              f'(installed on the system PATH)', file=sys.stderr)
        return 0
    return 0


def _location_lines(ctx):
    '''`<comp>\\t<abspath>` for every REQUESTED component whose driver manages a location
    (tarball/appImage/source/…); native/PATH components (no managed location) are omitted. Uses the
    TARGET location (no per-component get_installed probe), so it's subprocess-free and fast — a
    tarball tool's dir is the same whether or not it's installed (the glue snippet path-guards).
    One resilient resolve: an unroutable pick drops out, never blanks (or re-resolves) the list.'''
    r = ctx.routes
    try:
        names = list(ctx.config.requested())
    except Exception:                                    # noqa: BLE001 — no picks / bad config -> nothing
        names = []
    if not names:
        return []
    units, _errs = r.resolve_resilient(names)
    ctx.prepare_units(units)                             # honor scope + `locations:` for the glue cache
    seen, lines = set(), []
    for rc in units.values():
        if rc.comp in seen:
            continue
        drv = get_driver(rc.driver, ctx.runner, ctx.paths)
        if drv is None:
            continue
        try:
            loc = drv.location(rc)
        except Exception:                                # noqa: BLE001 — a driver hiccup skips one, not all
            loc = None
        if loc:
            s = str(loc)
            lines.append(f'{rc.comp}\t{ctx.paths.expand(s) if s.startswith(("~", "/")) else s}')
            seen.add(rc.comp)
    return lines


def write_location_cache(ctx, lines=None):
    '''Write the `<comp>\\t<path>` lines to the glue-locations cache the shell glue reads (so a normal
    shell startup is a file read, not a `configsys location --all` subprocess). Best-effort.'''
    if lines is None:
        lines = _location_lines(ctx)
    try:
        if ctx.runner.pretend:                           # pretend probes read empty: never cache that
            return
        p = ctx.paths.glue_locations_file
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(('\n'.join(lines) + '\n') if lines else '', encoding='utf-8')
    except Exception:                                    # noqa: BLE001 — a cache write must never fail an op
        pass


def _location_all(ctx):
    '''Bulk `location`: print every managed location for the requested set in ONE process, and refresh
    the cache file the shell glue reads. The glue calls this once on a cold/stale cache; thereafter it
    reads the file directly (~1ms) instead of paying a ~250ms Python startup every shell launch.'''
    lines = _location_lines(ctx)
    write_location_cache(ctx, lines)
    for line in lines:
        print(line)
    return 0


def cmd_versions(ctx, args):
    '''Show, per install method, the version it would install for a component — native vs
    tarball/source/… — with the newest ("tip") lag called out, and (with --min) which methods meet
    a floor. Read-only. The version each method offers comes from its driver's get_latest (cached
    machine-locally; --refresh re-queries).'''
    from ..resolve import ResolveError
    from .. import versionreport
    try:
        rep = versionreport.report(ctx, args.name, min_version=getattr(args, 'min_version', None),
                                   refresh=getattr(args, 'refresh', False))
    except ResolveError as e:
        print(f'configsys: {e}', file=sys.stderr)
        return 1
    if not rep.methods:
        print(f'configsys: {args.name} has no install method here', file=sys.stderr)
        return 1

    print(f'\n{rep.name}' + (f'   (tip {rep.tip})' if rep.tip else ''))
    width = max((len(f'{m.via} ({m.driver})' if m.via == "native" else m.via) for m in rep.methods),
                default=8)
    for m in rep.methods:
        label = f'{m.via} ({m.driver})' if m.via == 'native' else m.via
        ver = m.latest or '—'
        tags = []
        if m.is_pinned:
            tags.append('pinned')
        elif m.is_default:
            tags.append('default')
        if m.installed:
            tags.append(f'installed {m.installed}' if m.installed != m.latest else 'installed')
        if m.lags_tip:
            tags.append('lags tip')
        if m.meets_min is True:
            tags.append(f'meets ≥{rep.min_version}')
        elif m.meets_min is False:
            tags.append(f'below ≥{rep.min_version}')
        suffix = f'   [{", ".join(tags)}]' if tags else ''
        print(f'  {label:<{width}}  {ver}{suffix}')
        if getattr(m, 'note', None):
            print(f'  {"":<{width}}  ⚠ {m.note}')

    # --min guidance: if the default can't meet the floor but another method can, name the pin.
    if rep.min_version is not None and rep.default_meets_min is False:
        alt = [m.via for m in rep.methods if m.meets_min is True]
        if alt:
            verb = 'meets' if len(alt) == 1 else 'meet'
            print(f'\n  the default method is below {rep.min_version}; '
                  f'`configsys pin set {rep.name} {alt[0]}` to use {alt[0]} '
                  f'({", ".join(alt)} {verb} it)')
        else:
            print(f'\n  no method here meets {rep.min_version}')
    return 0
