'''check.py — the static ambiguity check.

The soundness promise of the `when:` model: for any two candidates (a component's
bindings, or a capability's providers) whose match-sets OVERLAP, one must be a subset
of the other. If every overlapping pair is comparable, resolution is provably
unambiguous for every possible machine. Any overlapping-but-incomparable pair is a
load-time error, pointing at a witness context — never a silent tiebreak.

Run check_all() when loading routes.hu to reject an ambiguous routes file up front.
'''

import re
from itertools import combinations

from . import predicate
from .errors import ConfigError, ConfigsysError
from .layers import as_list
from .resolve import SPECIAL_VIAS as _SPECIAL_VIA   # special vias that aren't Drivers


class AmbiguityError(ConfigsysError):
    '''Two overlapping-but-incomparable candidates — a load-time config error.'''


def gated(binding, cascade):
    '''`binding`'s `when:` intersected with the driver gate it is subject to (OsCascade.gate_pred —
    its via's `drivers:` `when:`, or for `via: native` the gate of each OS's manager): its TRUE
    candidate set, the same one resolve._matching filters by. Used to judge OVERLAP only —
    specificity stays on the raw `when:`, because resolution ranks raw `when:`s (the gate adds no
    specificity), so a same-via pair overlapping inside the gate must still be raw-comparable.'''
    gp = getattr(cascade, 'gate_pred', None)
    g = gp(binding.via) if gp is not None else None
    if g is None:
        return binding.pred
    node = predicate.And([binding.pred, g])
    raw = getattr(binding.pred, '_text', None)
    if raw is not None:                                # a memo key: the when plus which gate (C3)
        gates = getattr(cascade, 'driver_gates', None) or {}
        node._text = f'({raw}) and <gate {binding.via}: {sorted((k, v[0]) for k, v in gates.items())}>'
    return node


# Where a binding may make configsys write fetched bytes AS ROOT: apt keyrings and source lists, and
# a dnf .repo named by its id (review-2026-11-2 A10 / 2026-09 A10). Any other target is a load error.
_KEY_DIRS = ('/usr/share/keyrings/', '/etc/apt/keyrings/', '/etc/apt/trusted.gpg.d/')
_SOURCE_DIRS = ('/etc/apt/sources.list.d/',)
_REPO_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:+-]*$')


def _confined(path, dirs):
    s = str(path)
    return s.startswith(dirs) and '..' not in s.split('/') and '/' not in s[len(next(
        d for d in dirs if s.startswith(d))):]


def _bad_sha256(v):
    '''The first malformed digest in a binding's `sha256:` (scalar or nested map), or None.'''
    if v is None:
        return None
    if isinstance(v, dict):
        return next((b for b in map(_bad_sha256, v.values()) if b is not None), None)
    return None if isinstance(v, str) and re.fullmatch(r'[0-9a-fA-F]{64}', v) else str(v)


def vendor_path_problem(details):
    '''Why a binding's root-written vendor path is unsafe, or None: `pubkey-path:` / `apt-source:
    key-path:` must be a file directly in an apt keyring dir, `source-path:` / `apt-source: list:` a
    file directly in /etc/apt/sources.list.d/, and a dnf `repo-id:` a plain name (it becomes
    /etc/yum.repos.d/<id>.repo).'''
    d = details or {}
    src = d.get('apt-source') if isinstance(d.get('apt-source'), dict) else {}
    for label, val, dirs in (('pubkey-path', d.get('pubkey-path'), _KEY_DIRS),
                             ('apt-source key-path', src.get('key-path'), _KEY_DIRS),
                             ('source-path', d.get('source-path'), _SOURCE_DIRS),
                             ('apt-source list', src.get('list'), _SOURCE_DIRS)):
        if val is not None and not _confined(val, dirs):
            return f'`{label}: {val}` must be a file directly in {" or ".join(dirs)}'
    rid = d.get('repo-id')
    if rid is not None and not _REPO_ID.match(str(rid)):
        return f'`repo-id: {rid}` must be a plain name (letters, digits, . _ : + -)'
    return None


def check_component(name, component, cascade):
    '''Verify a component's bindings resolve unambiguously. Two bindings of the SAME `via:` that
    overlap must be comparable (one `when:` ⊆ the other) — else which variant of that one method
    wins is genuinely undefined and only `when:` can fix it. Two bindings of DIFFERENT `via:` MAY
    overlap incomparably: those are alternative install methods, and the driver-preference /
    `standing:` channel picks the default at resolve time (a true tie errors there, pointing at
    preference — never at `when:`). So `when:` stays validity-only and is never forced narrower.'''
    from .resolve import cpu_names
    for i, b in enumerate(component.bindings):
        m = b.details.get('cpu-names')
        if m is not None and not (isinstance(m, dict) and m and all(isinstance(v, str) for v in m.values())):
            raise ConfigError(f'component {name!r}: binding #{i} (via:{b.via}) `cpu-names:` must be a '
                              f'non-empty map {{ <cpu>: <upstream token> }}, e.g. {{ x86_64: amd64  aarch64: arm64 }}')
        bad = _bad_sha256(b.details.get('sha256'))
        if bad is not None:
            raise ConfigError(f'component {name!r}: binding #{i} (via:{b.via}) `sha256:` {bad!r} is not a '
                              '64-hex-digit digest (a scalar, or a map by cpu / package format)')
        if b.details.get('strip') is not None:
            from .driver import strip_count
            if strip_count(b.details['strip']) is None:
                raise ConfigError(f'component {name!r}: binding #{i} (via:{b.via}) `strip:` '
                                  f'{b.details["strip"]!r} is not a whole number of path components')
        why = vendor_path_problem(b.details)           # root writes stay in the keyring/source dirs (A10)
        if why:
            raise ConfigError(f'component {name!r}: binding #{i} (via:{b.via}) {why}')
        if b.via == 'appImage' and not b.details.get('path'):   # appimage-no-path (drivers-lang-26)
            raise ConfigError(f'component {name!r}: binding #{i} (via:appImage) has no `path:` — '
                              'the file the .AppImage is installed as (e.g. `$CONFIGSYS_APP_DIR/foo.AppImage`)')
        if b.via == 'script' and b.details.get('version-re') is not None:
            try:                                       # a bad regex fails here, not in every probe
                re.compile(str(b.details['version-re']))
            except re.error as e:
                raise ConfigError(f'component {name!r}: binding #{i} (via:script) `version-re:` '
                                  f'{b.details["version-re"]!r} is not a valid regex ({e})') from None
        if b.via == 'dotfiles':                        # paths a capture/relocate/backup acts on (A4)
            from .drivers.dotfiles import link_specs, spec_problem
            for _n, src, dst, absorb in link_specs(b.details):
                why = spec_problem(src, dst, absorb)
                if why:
                    raise ConfigError(f'component {name!r}: binding #{i} (via:dotfiles) {why}')
    for (i, a), (j, b) in combinations(enumerate(component.bindings), 2):
        if a.via != b.via:
            continue                                   # cross-method overlap: preference decides
        ma, mb = cpu_names(a.details), cpu_names(b.details)
        if ma and mb and not (set(ma) & set(mb)):
            continue                                   # disjoint cpu sets (cpu-names): never both valid
        ga, gb = gated(a, cascade), gated(b, cascade)   # overlap on the gated candidate set
        if predicate.overlap(ga, gb, cascade) and not predicate.comparable(a.pred, b.pred, cascade):
            raise AmbiguityError(
                f'component {name!r}: two via:{a.via} bindings (#{i} and #{j}) overlap but neither '
                f'is more specific (e.g. on {predicate.witness(ga, gb, cascade)}) — make '
                f'their when: comparable (one a subset of the other) or disjoint')


def _method_tie_warnings(name, component, cascade, never_auto_drivers=None):
    '''Cross-method (different via) bindings that overlap AND would tie under the built-in
    driver-preference (nothing separates them) — resolution errors on such a machine, so flag it
    at check time. Best-effort: a machine's own `driver-preference`/OS override can still fix it.
    `never_auto_drivers` = the vias whose `drivers:` block is `standing: never-auto` (defaults to the
    set routes.load stamped on the cascade) — excluded from the default pool exactly like
    resolve._select does, so a never-auto driver can't read as a false tie.'''
    from .resolve import _prefer_rank, _binding_never_auto, DEFAULT_DRIVER_PREFERENCE as order

    def rank(b):
        return (-_prefer_rank(b), order.index(b.via) if b.via in order else len(order))

    # a `standing: never-auto` binding is never eligible to be the auto-default, so it can never
    # TIE for it — resolution excludes it from the default pool. Mirror that here (else an opt-in
    # never-auto method overlapping an ordinary one reads as a false ambiguity).
    if never_auto_drivers is None:
        never_auto_drivers = getattr(cascade, 'never_auto_drivers', frozenset())
    eligible = [(i, b) for i, b in enumerate(component.bindings)
                if not _binding_never_auto(b) and b.via not in never_auto_drivers]

    out = []
    for (i, a), (j, b) in combinations(eligible, 2):
        if a.via == b.via or rank(a) != rank(b):
            continue
        # both must be CANDIDATES somewhere at once: overlap on the driver-gated sets (a gated-out
        # driver's binding never competes — the same filter resolve._matching applies)
        ga, gb = gated(a, cascade), gated(b, cascade)
        if not predicate.overlap(ga, gb, cascade):
            continue
        # a STRICT subset one way means most-specific resolves the default (no tie). A tie needs
        # equal or incomparable preds where they overlap — i.e. no strict subset either way.
        # (Specificity is on the RAW `when:` — resolution ignores the gate there.)
        sa = predicate.subset(a.pred, b.pred, cascade)
        sb = predicate.subset(b.pred, a.pred, cascade)
        if sa != sb:
            continue
        out.append(f'methods via:{a.via} and via:{b.via} overlap (e.g. on '
                   f'{predicate.witness(ga, gb, cascade)}) and are equally preferred '
                   f'by default — add a `driver-preference` order or a `standing:` rank to pick one')
    return out


def check_all(components, cascade):
    '''Validate every component. Raises AmbiguityError on the first offender. This is the
    fast load-time gate (ambiguity only — see validate() for the full lint).'''
    for name, component in components.items():
        check_component(name, component, cascade)


# -- full lint (for `configsys check`) ------------------------------------

class Issue:
    '''One problem found by validate(). `severity` is 'error' (definitely broken) or
    'warning' (localized — breaks only that component when used).'''

    def __init__(self, kind, message, component=None, source=None, severity='error'):
        self.kind = kind
        self.message = message
        self.component = component       # component name, or None (e.g. a driver issue)
        self.source = source             # the file it came from (provenance)
        self.severity = severity

    @property
    def is_error(self):
        return self.severity == 'error'




def _providable_caps(components, cascade):
    '''Every capability something could provide: each LIVE component's name + its provides
    (a removed `{}` component provides nothing), plus environment caps from the OS blocks.'''
    caps = set()
    for name, comp in components.items():
        if comp.bindings or comp.provides:
            caps.add(name)
            caps.update(comp.provides)
    for block in cascade.blocks:
        caps.update(cascade.provides(block))
    return caps


def _versioned_providers(components):
    '''cap -> [(provider_name, provided_version)] from every `provides: {cap: V}`, component- and
    binding-level. This is the population a versioned `requires:` constraint selects from (the
    resolver picks a provider whose provided version `meets()` the constraint), so it's exactly what
    decides whether a constraint is satisfiable at all.'''
    out = {}
    for name, comp in components.items():
        for cap, v in getattr(comp, 'prov_versions', {}).items():
            out.setdefault(cap, []).append((name, v))
        for b in comp.bindings:
            for cap, v in getattr(b, 'prov_versions', {}).items():
                out.setdefault(cap, []).append((name, v))
    return out


def _unsatisfiable(cap, constraint, vprov):
    '''A versioned require `{cap: constraint}` is unsatisfiable when `cap`'s providers all declare a
    CONCRETE provided version and none meets the constraint (`>=13` against providers 11/12). Returns
    the sorted "have" versions to name in the message, else None (satisfiable, or not our concern).

    ABSTAINS when any provider declares a FLOOR-style provided version (`cargo: ">=1.80"` — a rustup
    that installs the LATEST, unbounded upward): such a provider satisfies any upward require, so a
    `>=` floor is never unsatisfiable against it. Only the concrete version-scoped case (cuda-toolkit
    11/12) is a genuine impossibility. Absence of any provider is `dangling-requires`' job, not ours.'''
    from .versionsweep import meets, _pv
    havers = vprov.get(cap)
    if not havers:
        return None
    if any(_pv(v) is None for _n, v in havers):      # a floor/latest provider -> upward requires are met
        return None
    if any(meets(v, constraint) for _n, v in havers):
        return None
    return ', '.join(sorted({str(v) for _n, v in havers}))


def pin_constraint_conflicts(pins, components, valid_via):
    '''[message] for every provider-pin whose CONCRETE provided version fails a version constraint
    some component requires on that capability — e.g. `cuda-toolkit: cuda-toolkit-12` (provides 12)
    while cudnn-8 requires cuda-toolkit "<12". Such a pin can never resolve for that consumer, and
    otherwise only surfaces at install/inspect time. Component-level requires only (unconditional);
    a binding-level constraint is conditional on that method winning, so it's not flagged here.'''
    from .versionsweep import meets, _pv
    out = []
    for cap, prov in pins.items():
        if prov in valid_via or prov not in components:      # binding-pin / invalid -> not a provider-pin
            continue
        pv = getattr(components[prov], 'prov_versions', {}).get(cap)
        if pv is None or _pv(pv) is None:                    # no concrete provided version to judge
            continue
        for cname, comp in components.items():
            con = getattr(comp, 'req_versions', {}).get(cap)
            if con and not meets(pv, con):
                out.append(f"pin '{cap}: {prov}' (provides {cap} {pv}) conflicts with "
                           f"'{cname}' requiring {cap} {con!r}")
    return out


def retired_key_warnings(component):
    '''[message] for each retired preference key (`prefer:` / `opt-in:` / `candidate-only:`) on one of
    the component's bindings — inert there (they'd pass through as driver fields), so a value the
    author meant as a preference would silently do nothing. Mirrors layers._RETIRED_TOP_KEYS.'''
    from .routes import RETIRED_STANDING_KEYS
    out = []
    for i, b in enumerate(component.bindings):
        for k, why in RETIRED_STANDING_KEYS.items():
            if k in b.details:
                out.append(f'binding #{i} (via:{b.via}) `{k}:` is {why} — ignored')
    return out


def retired_driver_key_warnings(cascade):
    '''[(message, source)] for each retired preference key on a `drivers:` block (inert there too).'''
    from .routes import RETIRED_STANDING_KEYS
    out = []
    for drv, spec in sorted((getattr(cascade, 'driver_specs', None) or {}).items()):
        if not isinstance(spec, dict):
            continue
        for k, why in RETIRED_STANDING_KEYS.items():
            if k in spec:
                src = (getattr(cascade, 'driver_sources', None) or {}).get(drv)
                out.append((f'driver {drv!r}: `{k}:` is {why} — ignored', src))
    return out


_ISO_DATE = re.compile(r'\d{4}-\d{2}-\d{2}\Z')


def release_registry_issues(cascade):
    '''[(message, source)] for a malformed `releases:` registry on an OS block: on a block that
    doesn't own its version line, a key that isn't a version, a missing / unknown `status:`, an
    unknown field, a date that isn't YYYY-MM-DD. Warnings — the registry feeds maintenance tools,
    never resolution.'''
    from .osversion import parse_version
    from .routes import RELEASE_FIELDS, RELEASE_STATUSES
    out = []
    for block, spec in sorted(cascade.blocks.items()):
        table = (spec or {}).get('releases') if isinstance(spec, dict) else None
        if table is None:
            continue
        src = (getattr(cascade, 'os_sources', None) or {}).get(block)
        where = f'os {block!r} releases:'
        if not isinstance(table, dict):
            out.append((f'{where} must be a map of VERSION_ID -> {{ status: … }}', src))
            continue
        line = cascade.version_line(block)      # never None here: this block declares releases
        if line != block:
            out.append((f'{where} {block!r} reads its versions on the {line!r} line — declare '
                        'the releases there', src))
        for version, rel in table.items():
            label = f'{where} {version}'
            if not parse_version(version):
                out.append((f'{label}: not a version', src))
            if not isinstance(rel, dict):
                out.append((f'{label}: must be a map with at least `status:`', src))
                continue
            status = rel.get('status')
            if status not in RELEASE_STATUSES:
                out.append((f"{label}: status {status!r} — use one of {', '.join(RELEASE_STATUSES)}",
                            src))
            for key in sorted(set(rel) - RELEASE_FIELDS):
                out.append((f'{label}: unknown field {key!r}', src))
            for key in ('released', 'eol'):
                if key in rel and not _ISO_DATE.match(str(rel[key])):
                    out.append((f'{label}: {key}: {rel[key]!r} is not YYYY-MM-DD', src))
            if 'base' in rel:
                parts = str(rel['base']).split()
                if len(parts) != 2 or parts[0] not in cascade.blocks or not parse_version(parts[1]):
                    out.append((f"{label}: base: {rel['base']!r} — use \"<os block> <version>\", "
                                'e.g. "ubuntu 24.04"', src))
    return out


def os_block_issues(cascade, valid_via):
    '''[(message, source)] for `os:` blocks that can't be what they say: a `using:` parent no block
    defines (the lineage silently stops there — no `linux`, no `python3`, no native manager), a
    `using` cycle (reported once), a `native:` that names no driver, an unknown field.'''
    from .routes import OS_BLOCK_FIELDS
    out, cycles = [], set()
    for block, spec in sorted(cascade.blocks.items()):
        src = (getattr(cascade, 'os_sources', None) or {}).get(block)
        if spec is not None and not isinstance(spec, dict):
            out.append((f'os {block!r}: must be a map ({{ using: …  native: … }})', src))
            continue
        spec = spec or {}
        parent = spec.get('using')
        if parent is not None and parent not in cascade.blocks:
            out.append((f'os {block!r}: `using: {parent}` names no os block — its lineage stops at '
                        f'{block!r} (no linux, nothing it provides, no native manager)', src))
        seen, n = [], block
        while n in cascade.blocks and n not in seen:
            seen.append(n)
            blk = cascade.blocks.get(n)
            n = blk.get('using') if isinstance(blk, dict) else None
        if n in seen:                                  # walked back into the chain: a `using` cycle
            loop = seen[seen.index(n):]
            if frozenset(loop) not in cycles:
                cycles.add(frozenset(loop))
                out.append((f'os {block!r}: `using` cycle ' + ' -> '.join(loop + [n]), src))
        native = spec.get('native')
        if native is not None and str(native) not in valid_via:
            out.append((f'os {block!r}: `native: {native}` is not a known driver', src))
        for key in sorted(set(spec) - OS_BLOCK_FIELDS):
            out.append((f'os {block!r}: unknown field {key!r} (an os block takes '
                        f'{", ".join(sorted(OS_BLOCK_FIELDS))})', src))
    return out


def facet_name_issues(cascade):
    '''[(message, source)] for a facet named like an OS block: evaluation and the ambiguity check
    read such a versioned atom differently (a facet off this lineage, an OS on it) — rename one.'''
    return [(f'facet {name!r} has the name of an os block — a `when:` atom over it is read as the OS '
             f'on some machines and as the facet on others; rename the facet',
             (getattr(cascade, 'os_sources', None) or {}).get(name))
            for name in sorted(set(cascade.facet_specs) & set(cascade.blocks))]


def _atom_issues(pred, cascade, where):
    '''[(kind, message)] for a `when:`'s name atoms: an unknown OS (a typo), or a BARE atom naming a
    facet — facets are versioned (`cuda >= 12`) or categorical (`gpu:nvidia`), so `when: "gpu"`
    silently never matches.'''
    out = []
    for atom in predicate.os_atoms(pred):
        name = atom.name
        if name in cascade.blocks:
            continue
        if name in cascade.facet_specs:
            if atom.op is None:
                spec = cascade.facet_specs.get(name)
                kind = spec.get('kind') if isinstance(spec, dict) else None
                fix = f'{name} >= <version>' if kind == 'version' else f'{name}:<value>'
                out.append(('bare-facet', f'{where}when: "{name}" never matches — {name!r} is a facet; '
                                          f'write `{fix}`'))
            continue
        out.append(('unknown-os', f'{where}when: names unknown OS {name!r}'))
    return out


def _parts_cycles(components):
    '''Each distinct cycle through `via: parts` bindings (as a name list ending where it started).'''
    edges = {n: [p for b in c.bindings if b.via == 'parts' for p in _as_parts(b.details.get('parts'))]
             for n, c in components.items()}
    seen, out, done = set(), [], set()

    def walk(n, stack):
        if n in stack:
            cyc = stack[stack.index(n):] + [n]
            key = frozenset(cyc)
            if key not in seen:
                seen.add(key)
                out.append(cyc)
            return
        if n in done or n not in edges:
            return
        stack.append(n)
        for m in edges[n]:
            walk(m, stack)
        stack.pop()
        done.add(n)

    for n in sorted(edges):
        walk(n, [])
    return out


def _as_parts(v):
    return [v] if isinstance(v, str) else [x for x in (v or []) if isinstance(x, str)]


def validate(components, cascade, drivers, pending_vias=frozenset(), never_auto_drivers=None,
             components_checked=False):
    '''Lint the merged component set -> [Issue] (empty = clean). Covers ambiguity, unknown
    via: driver, unknown component in parts: (all errors), and when:-names-unknown-OS +
    requires-nothing-provides (warnings — localized). Attribution via each Component.source.

    `pending_vias` are via names provided by a declared code plugin that is present but not
    loaded (untrusted / incompatible): they're known-but-unavailable, so they don't count as
    unknown-via errors here — the app surfaces a single "trust the plugin" nudge instead.
    `components_checked` = every component already passed `check_component` (a validated
    routes.load returned them), so the ambiguity pass is skipped rather than run twice.'''
    from .drivers import supported_names
    from .resolve import cap_names, standing_problem
    valid_via = _SPECIAL_VIA | supported_names() | set(pending_vias)
    providable = _providable_caps(components, cascade)
    vprov = _versioned_providers(components)
    issues = []

    def add(kind, msg, comp, sev='error'):
        issues.append(Issue(kind, msg, comp.name, comp.source, sev))

    for cycle in _parts_cycles(components):            # a parts loop would error every resolve (B4)
        add('parts-cycle', 'parts cycle: ' + ' -> '.join(cycle), components[cycle[0]])
    for name, comp in components.items():
        if not components_checked:
            try:
                check_component(name, comp, cascade)
            except AmbiguityError as e:
                add('ambiguity', str(e), comp)
        for msg in _method_tie_warnings(name, comp, cascade, never_auto_drivers):
            add('method-tie', msg, comp, 'warning')
        for msg in retired_key_warnings(comp):
            add('retired-key', msg, comp, 'warning')
        why = standing_problem({'standing': getattr(comp, 'standing', None)})
        if why:
            add('bad-standing', why, comp, 'warning')
        if getattr(comp, 'parts_ignored', False):
            add('parts-ignored', 'component-level `parts:` is ignored because the component also has '
                '`install:` methods — put the bundle on a `{ via: parts  parts: [...] }` binding (or '
                'drop `install:` to make it a pure bundle)', comp, 'warning')
        # a version constraint whose operand doesn't parse (`>=3.1x`) abstains at resolve time (never
        # met) — say so here, where it can be fixed (B4)
        from .osversion import parse_constraint
        for where, cons in [('requires', getattr(comp, 'req_versions', {}) or {})] + [
                (f'binding via:{b.via} requires', getattr(b, 'req_versions', {}) or {}) for b in comp.bindings]:
            for cap, c in cons.items():
                clauses = parse_constraint(str(c)) if c else None
                if c and (not clauses or any(tgt is None for _op, tgt in clauses)):
                    add('bad-constraint', f'{where} {cap}: {c!r} is not a version constraint '
                        '(e.g. ">=3.11", ">=1.2,<2") — it is never met', comp)
        for b in comp.bindings:
            if b.via not in valid_via:
                add('unknown-via', f'via:{b.via!r} is not a known driver', comp)
            # a versioned atom naming a declared facet (`cuda >= 12`) is a version FACET, not an OS
            # typo; a BARE one never matches (facets are versioned/categorical) — routing-22
            for kind, msg in _atom_issues(b.pred, cascade, ''):
                add(kind, msg, comp, 'warning')
            why = standing_problem(b.details)
            if why:
                add('bad-standing', f'binding via:{b.via} {why}', comp, 'warning')
            if b.via == 'parts':
                for part in as_list(b.details.get('parts')):
                    if part not in components:
                        add('unknown-part', f'parts references unknown component {part!r}', comp)
            if b.via == 'script':
                if not b.details.get('install-cmd'):
                    add('script-no-install', 'via:script needs an install-cmd', comp)
                if not b.details.get('uninstall-cmd'):
                    add('script-no-uninstall', 'via:script has no uninstall-cmd — configsys '
                        'cannot cleanly remove it (install still allowed)', comp, 'warning')
            if b.via == 'tarball' and not b.details.get('installDir') and not b.details.get('locations'):
                # a tarball install dir is rm -rf'd on every (re)install; a missing installDir
                # resolves to the bare scope base ($HOME / /opt) -> catastrophic. Require a dedicated one.
                add('tarball-no-installdir', 'via:tarball needs an installDir (it is rm -rf\'d on '
                    '(re)install; a missing one resolves to the scope base — $HOME/opt)', comp)
            for cap in cap_names(b.details.get('requires')):   # cap_names: tolerates versioned {cap: floor} entries
                if cap not in providable:
                    add('dangling-requires', f'requires {cap!r} which nothing provides', comp, 'warning')
            for cap, con in getattr(b, 'req_versions', {}).items():
                have = _unsatisfiable(cap, con, vprov)
                if have is not None:
                    add('unsatisfiable-constraint', f'via:{b.via} requires {cap} {con!r} but no '
                        f'provider satisfies it (have: {have})', comp, 'warning')
        for cap in comp.requires:
            if cap not in providable:
                add('dangling-requires', f'requires {cap!r} which nothing provides', comp, 'warning')
        for cap, con in getattr(comp, 'req_versions', {}).items():
            have = _unsatisfiable(cap, con, vprov)
            if have is not None:
                add('unsatisfiable-constraint', f'requires {cap} {con!r} but no provider satisfies '
                    f'it (have: {have})', comp, 'warning')

    for drv, (text, gate) in sorted((getattr(cascade, 'driver_gates', None) or {}).items()):
        src = (getattr(cascade, 'driver_sources', None) or {}).get(drv)
        for kind, msg in _atom_issues(gate, cascade, f'driver {drv!r}: '):
            issues.append(Issue(kind, msg, None, src, 'warning'))
    for drv, spec in sorted((getattr(cascade, 'driver_specs', None) or {}).items()):
        why = standing_problem(spec)
        if why:
            issues.append(Issue('bad-standing', f'driver {drv!r}: {why}', None,
                                (getattr(cascade, 'driver_sources', None) or {}).get(drv), 'warning'))
    for msg, src in os_block_issues(cascade, valid_via):
        issues.append(Issue('os-block', msg, None, src, 'warning'))
    for msg, src in facet_name_issues(cascade):
        issues.append(Issue('facet-collision', msg, None, src, 'error'))
    for msg, src in retired_driver_key_warnings(cascade):
        issues.append(Issue('retired-key', msg, None, src, 'warning'))
    for msg, src in getattr(cascade, 'knobs_ignored', None) or ():   # a plugin's preference knobs
        issues.append(Issue('plugin-preference', msg, None, src, 'warning'))
    for msg, src in release_registry_issues(cascade):
        issues.append(Issue('os-release', msg, None, src, 'warning'))
    for drv, reqs in drivers.items():
        for cap in reqs:
            if cap not in providable:
                issues.append(Issue('dangling-requires',
                    f'driver {drv!r} requires {cap!r} which nothing provides',
                    None, None, 'warning'))
    return issues
