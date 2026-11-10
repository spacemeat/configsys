'''routes.py — load routes.hu into an OS cascade + components, and the app-facing Resolver.

Turns humon nodes into small dataclasses the resolver walks (OsCascade / Component /
Binding), validates the file (ambiguity check), and exposes `Resolver`: the object the app
holds to turn component names (this machine's picks, or the names an op is given) into the
`{key: ResolvedComponent}` closure for this machine's context. Resolution itself lives in
resolve.py; the RC marshalling in adapt.py.
'''

import os
from collections import namedtuple

from . import layers, predicate
from .errors import ConfigError, ConfigsysError
from .layers import as_list
from .resolve import NEVER_AUTO, _standing, cap_constraints, cap_names


class Binding:
    def __init__(self, spec):
        spec = dict(spec)
        self.source = spec.pop('__source__', None)   # layer that contributed this binding (merge)
        spec.pop('drop', None)                        # a merge directive, never install data
        self.when = spec.pop('when', None)
        self.pred = predicate.parse(self.when)
        self.via = spec.pop('via', None)
        if self.via is None:                          # a load error (forgiven for a plugin), never a crash
            raise ConfigError(f'binding without `via`: {spec}')
        self.details = spec               # everything else (name, app, foreign-arch, ...)
        # versioned deps declared on THIS binding (stage 2): {cap: constraint} for a binding-level
        # `requires: [ { cargo: ">=1.96" } ]`, and {cap: floor} for a `provides: { cargo: 1.97 }`
        # (the version THIS method guarantees). Names still flow through the resolver unchanged
        # (cap_names); these maps carry the versions for the sweep + floor-aware resolution.
        self.req_versions = cap_constraints(self.details.get('requires'))
        self.prov_versions = cap_constraints(self.details.get('provides'))


# top-level keys a component may carry; anything else is a typo or a removed construct
# (e.g. the old inline `dotfiles:` node) and must fail loudly, not vanish silently.
_COMPONENT_KEYS = frozenset({'provides', 'requires', 'suggests', 'parts', 'install', 'standing',
                             'description', 'attrs'})

# The retired preference trio, replaced by the ONE `standing:` knob (routing-model §8). At component
# level they are unknown-key load errors (with this hint); on a binding / a `drivers:` block they would
# be inert driver fields, so routecheck.validate warns about them (mirrors layers._RETIRED_TOP_KEYS).
RETIRED_STANDING_KEYS = {
    'prefer':         'retired — use `standing: <integer>` (a preference rank, higher wins)',
    'opt-in':         'retired — use `standing: never-auto`',
    'candidate-only': 'retired — use `standing: never-auto`',
}

# Attrs auto-derived from a component's install methods — companion/asset kinds tag themselves, so
# the -dotfiles/-service companions and font components need no hand-authored `attrs:` (see
# docs/component-attrs.md). Union'd with authored attrs.
_VIA_ATTR = {'dotfiles': 'dotfiles', 'glue': 'glue', 'service': 'service', 'font': 'font', 'group': 'group'}


def _derived_attrs(bindings):
    out = []
    for b in bindings:
        a = _VIA_ATTR.get(getattr(b, 'via', None))
        if a and a not in out:
            out.append(a)
    return out
# the non-`install` fields, which merge with inheritance (a layer that omits one keeps the lower).
_COMPONENT_FIELDS = ('provides', 'requires', 'suggests', 'parts', 'standing', 'description')


def _check_component_keys(name, spec):
    unknown = set(spec) - _COMPONENT_KEYS
    if unknown:
        hint = ''
        if 'dotfiles' in unknown:  # the removed inline-node construct
            hint = '; config is a required `<name>-dotfiles` component now, not a `dotfiles:` field'
        retired = sorted(unknown & set(RETIRED_STANDING_KEYS))
        if retired:                # the old preference trio -> the one `standing:` knob
            hint += '; ' + '; '.join(f'`{k}:` is {RETIRED_STANDING_KEYS[k]}' for k in retired)
        raise ConfigError(
            f'component {name!r}: unknown key(s) {sorted(unknown)}; '
            f'valid keys are {sorted(_COMPONENT_KEYS)}{hint}')


def _binding_identity(b):
    '''A binding's merge identity: (via, when-as-written, the cpus it covers or None). The cpus come
    from `cpu-names:` (or a cpu-keyed `asset:`), so two disjoint-cpu twins of one via + when — the
    x86_64 and aarch64 tarballs of one release — are two bindings, not one silently collapsing into
    the other (they used to need a dummy `when: "linux"` to stay apart). A higher-layer binding with
    the same identity OVERRIDES the lower; one that names no cpus overrides every same (via, when)
    binding below it; a `drop:` retracts them the same way.'''
    cpus = b.get('cpu-names')
    if not isinstance(cpus, dict):
        asset = b.get('asset')
        cpus = asset if isinstance(asset, dict) and not ({'deb', 'rpm', 'pacman'} & set(asset)) else None
    key = tuple(sorted(cpus)) if isinstance(cpus, dict) and cpus else None
    return (b.get('via'), None if b.get('when') is None else str(b.get('when')).strip(), key)


def _not_a_map(val):
    '''A component value that is neither a definition (a map) nor a removal (`{}` / empty).'''
    return not isinstance(val, dict) and val not in (None, '')


def _merge_component_chain(name, chain):
    '''Merge a component's per-layer definitions (ascending precedence) into one spec, ADDITIVELY:
    - an empty spec `{}` is a TOMBSTONE — it clears everything accumulated so far (whole-component
      removal, the unchanged `{}` convention);
    - `install:` bindings UNION keyed by (via, when): a higher binding with the same identity
      overrides the lower, a `drop:` binding retracts the matching inherited one;
    - the other fields (provides/requires/suggests/parts/standing) override with inheritance.
    Each surviving binding is tagged `__source__` with the layer that contributed it (so a dotfiles
    binding's content root, and provenance, follow the defining layer even across an amend), and
    the spec carries `__requires_source__`, the layer whose component-level `requires:` stands (a
    `version-floors:` patch from below it doesn't override its floors — _apply_version_floors).'''
    fields, bindings, attrs = {}, {}, []   # bindings: (via, when) -> spec dict (insertion order kept)
    req_src = None
    for val, src in chain:
        if _not_a_map(val):                # `foo: bar` is a typo, never a silent tombstone (routing-25)
            raise ConfigError(f'component {name!r}: expected a map ({{ install: [ … ] }}, or {{}} to '
                              f'remove it), got {val!r}')
        spec = val if isinstance(val, dict) else {}
        _check_component_keys(name, spec)
        if not spec:                   # {} tombstone: forget everything below, start fresh
            fields, bindings, attrs, req_src = {}, {}, [], None
            continue
        for k in _COMPONENT_FIELDS:
            if k in spec:
                fields[k] = spec[k]
        if 'requires' in spec:
            req_src = src
        for a in as_list(spec.get('attrs')):   # attrs UNION across layers (a plugin can add tags)
            if a not in attrs:
                attrs.append(a)
        for b in (spec.get('install') or []):
            ident = _binding_identity(b)
            # a binding naming no cpus speaks for every same (via, when) binding below it
            covered = ([k for k in bindings if k[:2] == ident[:2]] if ident[2] is None
                       else [ident] if ident in bindings else [])
            if _truthy(b.get('drop')):
                for k in covered:
                    bindings.pop(k, None)
                continue
            for k in covered:
                if k != ident:
                    bindings.pop(k, None)
            bindings[ident] = {**b, '__source__': src}
    out = {**fields, 'install': list(bindings.values())}
    if attrs:
        out['attrs'] = attrs
    if req_src is not None:
        out['__requires_source__'] = req_src
    return out


class Component:
    def __init__(self, name, spec, checked=False):
        self.source = None       # file this definition came from (provenance for `where`)
        self.shadows = False     # True if more than one layer contributed to this component
        if not checked:          # _merge_component_chain already checked each layer's spec
            _check_component_keys(name, spec)
        self.name = name
        # provides/requires/suggests carry NAMES (resolver closes on these, unchanged) plus, for
        # any versioned `{ cap: constraint }` entries, a parallel constraint map (stage 2): the
        # component-level version floors, read by the sweep + floor-aware resolution.
        self.provides = cap_names(spec.get('provides'))
        self.prov_versions = cap_constraints(spec.get('provides'))
        self.requires = cap_names(spec.get('requires'))
        self.req_versions = cap_constraints(spec.get('requires'))
        self.requires_source = spec.get('__requires_source__')   # layer whose `requires:` stands
        self.suggests = cap_names(spec.get('suggests'))   # soft deps: pulled if resolvable, else skipped
        self.parts = as_list(spec.get('parts'))
        # a `standing: never-auto` provider satisfies a `requires:` only when explicitly wanted /
        # provider-pinned / version-constrained — NEVER auto-pulled to close someone else's
        # requirement. For best-effort/caveated providers (e.g. gcompat, a glibc shim) or the
        # non-default of a versioned pair. See resolve.py `_satisfy`.
        self.standing = spec.get('standing')   # as written (routecheck lints a garbled one)
        _st = _standing(spec)
        self.never_auto = _st == NEVER_AUTO
        # an INTEGER component `standing:` RANKS this component among the providers of a capability
        # (higher wins) when several could auto-satisfy a `requires:` — resolve._pick_provider. 0 =
        # unranked (the default); a strict top rank resolves what would otherwise be an ambiguity.
        self.standing_rank = _st if isinstance(_st, int) else 0
        # optional one-line human description (names can be esoteric); shown in the TUI. Empty if
        # unset — populated incrementally in routes.hu/plugins.
        self.description = str(spec.get('description') or '')
        self.bindings = [Binding(b) for b in (spec.get('install') or [])]
        # component-level `parts:` with no `install:` of its own is shorthand for the aggregator
        # binding `{ via: parts  parts: [...] }` (a bundle = the union of its parts, no unit of its
        # own). With an `install:` too it can't mean that — it stays inert and routecheck warns
        # (`parts_ignored`); per-OS bundles put `parts:` on a `when:`-gated `via: parts` binding.
        self.parts_ignored = bool(self.parts) and bool(self.bindings)
        if self.parts and not self.bindings:
            self.bindings = [Binding({'via': 'parts', 'parts': list(self.parts)})]
        # Component attributes (attrs:) — cross-cutting tags for filtering, ORTHOGONAL to profiles
        # (interface CLI/TUI/GUI, role lib/SDK/app, license FOSS/GNU/proprietary [free-form multi],
        # data tele, ...). Case preserved as authored; the eventual filter matches case-insensitively.
        # Authored tags are UNIONed with a few derived from the route (via:dotfiles -> `dotfiles`,
        # via:service -> `service`, via:font -> `font`). See docs/component-attrs.md.
        seen, self.attrs = set(), []
        for a in [str(x) for x in as_list(spec.get('attrs'))] + _derived_attrs(self.bindings):
            if a.lower() not in seen:
                seen.add(a.lower())
                self.attrs.append(a)


def _truthy(v):
    from .layers import parse_bool                     # the one bool spelling (D1)
    return parse_bool(v, False)


# The release registry: an OS block that owns a version line may carry `releases: { <VERSION_ID>:
# { status: … } }` — which releases exist and what each ships. Read by the maintenance tools
# (tools/osaudit.py, the /update-os skill). The resolver reads ONE field: a derivative release's
# `base: "<block> <version>"` (OsCascade.bases_of — D8), so versioned atoms on the base's scale reach
# it (docs/routing-model.md §6).
RELEASE_STATUSES = ('prerelease', 'released', 'eol')

# the fields an `os:` block may carry (routecheck warns `os-block` on any other — a typo'd `usings:`
# would otherwise leave the block cut off from its lineage without a word)
OS_BLOCK_FIELDS = frozenset({'using', 'native', 'scale-root', 'provides', 'detect', 'driver-preference',
                             'releases', 'advisory'})
RELEASE_FIELDS = frozenset({'status', 'released', 'eol', 'codename', 'image', 'glibc', 'python3',
                            'gcc', 'manager', 'note', 'base'})


def _release_bases(os_dict):
    '''{block: {version tuple: (base block, base version tuple)}} from each os block's
    `releases: { <v>: { base: "<block> <version>" } }` (a malformed `base:` is skipped; `check`
    lints the registry).'''
    out = {}
    for name, blk in (os_dict or {}).items():
        rels = blk.get('releases') if isinstance(blk, dict) else None
        for ver, entry in (rels.items() if isinstance(rels, dict) else ()):
            base = entry.get('base') if isinstance(entry, dict) else None
            parts = str(base or '').split()
            if len(parts) != 2:
                continue
            try:
                out.setdefault(name, {})[tuple(predicate.parse_version(str(ver)))] = (
                    parts[0], tuple(predicate.parse_version(parts[1])))
            except Exception:                          # noqa: BLE001 — a bad version: skipped
                continue
    return out


class OsCascade:
    '''The OS layer: `using` inheritance, the `native` driver, scale-roots, and the
    capabilities each environment provides for free.'''

    def __init__(self, os_dict, facet_specs=None):
        self.blocks = os_dict
        self.scale_roots = {n for n, b in os_dict.items()
                            if isinstance(b, dict) and _truthy(b.get('scale-root'))}
        self.facet_specs = facet_specs or {}   # declared `facets:` {name: {kind, detect, …}}
        self.facets_cat = {}                   # detected {ns: frozenset(tags)}  (set by detect_facets)
        self.facets_ver = {}                   # detected {name: version string}
        self.driver_specs = {}                 # raw merged `drivers:` blocks (set by load)
        self.driver_sources = {}               # {driver: file whose block wins} (provenance)
        self.os_sources = {}                   # {os block: file whose block wins} (provenance)
        self.never_auto_drivers = frozenset()      # vias whose driver block is `standing: never-auto`
        # driver-wide VALIDITY gates: {driver: (when-text, Predicate)} from a `drivers:` block's
        # `when:` (set by load). A binding whose driver's gate is false here is not a candidate —
        # like a false binding `when:` — but the gate adds NO specificity (validity-only, like
        # `cpu-names:`). Applies to a `via: native` binding that reaches that manager too.
        self.driver_gates = {}
        self._gate_pred_cache = {}
        # D8 (review-2026-11-2): a derivative release's `base:` in the release registry —
        # {scale-root block: {version tuple: (base scale-root block, base version tuple)}} — so
        # `ubuntu >= 24.04` reaches Zorin 18 / Mint 22 without hand-listing every derivative.
        self.release_bases = _release_bases(os_dict)

    def bases_of(self, block, version):
        '''{scale-root: version} this machine ALSO counts as for versioned atoms: the base its
        registered release names, and that base's own base, … ({} for a release the registry doesn't
        know — `check` says so — or a line with no bases).'''
        lineage = self.lineage(block)
        sroot = next((n for n in lineage if n in self.scale_roots), None)
        v = predicate.parse_version(version) if isinstance(version, str) else version
        out = {}
        while sroot is not None and v is not None and sroot in self.release_bases:
            hit = self.release_bases[sroot].get(tuple(v))
            if hit is None or hit[0] in out:
                break
            out[hit[0]] = hit[1]
            sroot, v = hit
        return out

    def provides(self, block):
        '''Capabilities baseline in this environment (union over the lineage's blocks).'''
        caps = set()
        for n in self.lineage(block):
            caps.update(as_list((self.blocks[n] or {}).get('provides')))
        return caps

    def lineage(self, name):
        '''Leaf-first chain following `using` to the root (cached: blocks are fixed once loaded).'''
        cache = self.__dict__.setdefault('_lineage_cache', {})
        hit = cache.get(name)
        if hit is not None:
            return list(hit)
        chain = self._lineage(name)
        cache[name] = tuple(chain)
        return chain

    def _lineage(self, name):
        chain, seen = [], set()
        while name and name not in seen and name in self.blocks:
            chain.append(name)
            seen.add(name)
            blk = self.blocks[name] or {}
            name = blk.get('using')
        return chain

    def native(self, name):
        '''The nearest `native:` driver walking the lineage (None if none set).'''
        for n in self.lineage(name):
            mech = (self.blocks[n] or {}).get('native')
            if mech:
                return mech
        return None

    def version_line(self, block):
        '''The block whose numbering `block`'s VERSION_ID is read in — its nearest scale-root,
        else (a line with no scale-root above it, like alpine) the nearest block declaring
        `releases:`; None for a rolling block.'''
        chain = self.lineage(block)
        for n in chain:
            if n in self.scale_roots:
                return n
        for n in chain:
            if (self.blocks.get(n) or {}).get('releases'):
                return n
        return None

    def releases(self, block):
        '''{VERSION_ID: {field: value}} — the release registry of `block`'s version line ({} when
        none is declared, or the block is rolling).'''
        line = self.version_line(block)
        table = (self.blocks.get(line) or {}).get('releases') if line else None
        return table if isinstance(table, dict) else {}

    def advisory(self, block):
        '''The nearest `advisory:` walking `block`'s lineage — an OS caveat the diagnostics show (the
        `!` page, `inspect`) on that block and every block that `using:`s it; a block's own replaces
        its parent's, and `advisory: ""` silences it. Whitespace-normalized, so the text may be
        written across lines. None when there is none (app-cli-25).'''
        for n in self.lineage(block):
            spec = self.blocks.get(n)
            if isinstance(spec, dict) and 'advisory' in spec:
                return ' '.join(str(spec['advisory'] or '').split()) or None
        return None

    def is_descendant(self, x, y):
        '''True if y is ancestor-or-self of x (x's subtree ⊆ y's subtree).'''
        return y in self.lineage(x)

    def context(self, block, version=None, cpu=None, disabled=()):
        native = self.native(block)
        ctx = predicate.Context(self.lineage(block), version, cpu, self.scale_roots,
                                facets_cat=self.facets_cat, facets_ver=self.facets_ver,
                                disabled=disabled, has_native=native is not None,
                                base_versions=self.bases_of(block, version))
        # the driver gates evaluated ONCE for this machine: resolve._matching drops every binding
        # of a gated-out driver (and a `via: native` binding when this OS's manager is gated out)
        ctx.native_driver = native
        ctx.gated_drivers = frozenset(d for d, (_t, p) in self.driver_gates.items()
                                      if not p.eval(ctx))
        # the untrusted plugin layer files: their command-carrying bindings aren't candidates
        # (trustgate.gated — review-2026-11-2 A1)
        ctx.untrusted_sources = getattr(self, 'untrusted_sources', frozenset())
        return ctx

    def gate_pred(self, via):
        '''The driver gate a binding of `via` is subject to, as a predicate over machines — None when
        ungated. For `via: native` it is the conjunction, over every gated manager M, of "this OS's
        native manager isn't M, or M's gate holds" (exact per OS leaf: a descendant that overrides
        `native:` is carved out). routecheck intersects a binding's `when:` with this to judge
        OVERLAP on the true candidate set; specificity stays on the raw `when:` (the gate adds none).
        Cached — gates are fixed once load() sets them.'''
        if via in self._gate_pred_cache:
            return self._gate_pred_cache[via]
        out = None
        if via == 'native':
            terms = []
            for mgr, (_t, gate) in sorted(self.driver_gates.items()):
                is_mgr = self._native_is(mgr)
                if is_mgr is not None:
                    terms.append(predicate.Or([predicate.Not(is_mgr), gate]))
            out = predicate.And(terms) if terms else None
        elif via in self.driver_gates:
            out = self.driver_gates[via][1]
        self._gate_pred_cache[via] = out
        return out

    def _native_is(self, mgr):
        '''A predicate true exactly on the OS leaves whose nearest `native:` is `mgr` (None if none).'''
        terms = []
        for n in self.blocks:
            if self.native(n) != mgr:
                continue
            carve = [predicate.Not(predicate.Os(d)) for d in self.blocks
                     if d != n and self.is_descendant(d, n) and self.native(d) != mgr]
            terms.append(predicate.And([predicate.Os(n)] + carve))
        return predicate.Or(terms) if terms else None


def _pf(entry):
    '''Normalize a plugin_files entry to (path, role). Accepts a bare path (defaults to the
    `plugin` role — used by tests/older callers) or an already-roled (path, role) tuple.'''
    if isinstance(entry, (tuple, list)):
        return (entry[0], entry[1] if len(entry) > 1 else 'plugin')
    return (entry, 'plugin')


# what `load` returns — named, and still a 4-tuple so every `c, comps, drv, na = load(…)` works (F2)
Loaded = namedtuple('Loaded', 'cascade components drivers never_auto_drivers')


# Validation memo (review-2026-11-2 tests-tools-05): routecheck over ~830 components is three
# quarters of a load (≈0.3 s of 0.4). Its verdict depends only on the layer files and the trust split,
# so a stack whose every file has the same CONTENT as one that already validated cleanly skips it —
# every command, every TUI reload after an edit to another file, and most of the test suite.
_VALIDATED = set()


def _stack_fingerprint(layer_list, untrusted_sources):
    import hashlib
    parts = []
    for lyr in layer_list:
        try:
            with open(lyr.path, 'rb') as f:
                digest = hashlib.sha1(f.read()).hexdigest()
        except OSError:
            return None
        parts.append((os.path.normpath(lyr.path), lyr.role, digest))
    return (tuple(parts), untrusted_sources)


def os_blocks(path, overrides_path=None, plugin_files=()):
    '''{block: spec} — only the merged `os:` section of the layer stack load() reads (no components,
    no route check): what a forced `--os` block is checked against before a command that may never
    need the catalog (`show`, `keys`) runs (app-cli-20).'''
    roots = [(path, 'repo')] + [_pf(p) for p in plugin_files]
    if overrides_path is not None:
        roots.append((overrides_path, 'user'))
    layer_list, _warnings = layers.expand_tolerant(roots, {'plugin', 'primary'})
    return layers.merge_dict_section(layer_list, 'os', layers.ALL_ROLES)


def load(path, overrides_path=None, plugin_files=(), validate=True,
         warnings_out=None, layers_out=None, command_trust=None, home=None):
    '''-> Loaded(cascade: OsCascade, components: {component_name: Component}, drivers: {driver:
    [required caps]}, never_auto_drivers: frozenset of vias whose `drivers:` block is `standing:
    never-auto`) — a named tuple, so positional unpacking still works.

    Layer stack lowest-first: routes.hu (repo) < plugin data files (the primary last) < the user's
    config, each with its `include:` graph expanded. Components merge PER NAME ADDITIVELY (union of
    install bindings by (via, when, cpus) identity; higher layer overrides a matching binding, `drop:`
    retracts one, `{}` removes the whole component — see _merge_component_chain); os/drivers merge
    from every layer, the top config last (a plugin may add a derivative-distro os block; an ordinary
    plugin's preference knobs on a block it didn't define are dropped — _plugin_knobs_ignored). A
    malformed plugin file is skipped (never bricks the rest). validate=True rejects an ambiguous set
    (skipped for a layer stack already validated clean — _VALIDATED). If a list is passed as
    `warnings_out`,
    skipped files/components are appended to it (for the diagnostics view) — the return value is
    unchanged so existing callers are unaffected. `home` is the configsys home a `~` include
    expands against (Paths.home).
    '''
    roots = [(path, 'repo')]
    roots += [_pf(p) for p in plugin_files]          # (path, role): 'primary' or 'plugin'
    if overrides_path is not None:
        roots.append((overrides_path, 'user'))
    layer_list, _warnings = layers.expand_tolerant(roots, {'plugin', 'primary'}, home=home)
    if warnings_out is not None:
        warnings_out.extend(_warnings)
    if layers_out is not None:                       # (path, role) low→high, for `-v` reporting
        layers_out.extend(layer_list)

    # SECURITY: a `facets: { detect: … }` probe runs a shell command on EVERY resolve/startup, with
    # no install and no user action. So facets are command-carrying data (like via:script/source): the
    # repo's always merge; a plugin's merge ONLY when that plugin is content-TRUSTED (`command_trust`,
    # from plugins.command_source_trusted). An untrusted plugin's facets are dropped with an
    # actionable warning — never silent, never blanket-refused (a trusted plugin gets its probes).
    # TRUST (review-2026-11-2 A1): the plugin layer files that aren't content-trusted. Their bindings
    # stay visible, but only plain packages-by-name from a trusted registry are candidates
    # (trustgate.gated, read off every context) — repos, keys, downloads, builds, scripts, glue and
    # dotfiles from them wait for `configsys plugin trust`.
    untrusted_sources = frozenset(
        os.path.normpath(lyr.path) for lyr in layer_list
        if lyr.role in ('plugin', 'primary', 'include') and command_trust is not None
        and not command_trust(lyr.path))

    def _facet_ok(lyr):
        if lyr.role == 'repo':
            return True
        # a plugin/primary file — or a file some layer INCLUDES — merges its probes only when
        # trusted. Trust follows the FILE'S LOCATION, not its includer: command_trust attributes a
        # file inside a synced plugin's checkout to that plugin and any other file to the user (a
        # plugin's own includes must stay inside its checkout — layers._visit). No
        # `command_trust` at all is NOT trust: a probe runs shell, so the default fails closed — a
        # caller that has vetted its plugins says so (`command_trust=lambda p: True`; routing-26).
        if lyr.role in ('plugin', 'primary', 'include'):
            return command_trust is not None and command_trust(lyr.path)
        return False
    facets = {}
    for _lyr in layer_list:
        _fd = _lyr.data.get('facets')
        if not (isinstance(_fd, dict) and _fd):
            continue
        if _lyr.role == 'user':
            # the TOP config's `facets:` is a VALUE map (`facets: { gpu: nvidia }` — a declared machine
            # fact, read by Resolver via layers.read_setting), never a probe spec: skip it here
            # silently. Only a spec-shaped (map) entry there is flagged — spec definitions belong in a
            # plugin (or the repo), and a map can't be a value.
            for _n, _v in _fd.items():
                if isinstance(_v, dict) and warnings_out is not None:
                    warnings_out.append(f'{_lyr.path}: facet {_n!r} — the top config\'s `facets:` holds '
                                        f'VALUES (e.g. `{_n}: nvidia`), not probe specs; define the '
                                        f'facet in a plugin — ignored')
            continue
        if not _facet_ok(_lyr):
            if warnings_out is not None:
                warnings_out.append(f'{_lyr.path}: `facets:` from an untrusted plugin is ignored — '
                                    f'run `configsys plugin trust <name>` to enable its '
                                    f'hardware/env probes')
            continue
        for _n, _spec in _fd.items():                # later layer wins per facet name
            if not isinstance(_spec, dict):
                # a non-map spec (e.g. a VALUE `gpu: nvidia` written in a plugin/primary) can't be
                # probed — skip it with a clear warning rather than crash detect_facets later.
                if warnings_out is not None:
                    warnings_out.append(f'{_lyr.path}: facet {_n!r} is not a spec map '
                                        f'({{ kind: categorical|version  detect: …  match: … }}) — '
                                        f'skipped (a facet VALUE override belongs in your top '
                                        f'config\'s `facets:`)')
                continue
            facets[_n] = _spec
    # os / drivers are DEFINITIONS: every layer may contribute (the uniform layer rule) — a plugin's
    # derivative-distro block, an include's, or a machine-local tweak in the TOP config (highest
    # precedence, e.g. `drivers: { snap: { standing: never-auto } }` on this box only). Except the
    # PREFERENCE KNOBS of an ordinary plugin on a block it didn't define (_plugin_knobs_ignored).
    knob_layers, knobs_ignored = _plugin_knobs_ignored(layer_list, plugin_files)
    cascade = OsCascade(layers.merge_dict_section(knob_layers, 'os', layers.ALL_ROLES), facets)
    cascade.untrusted_sources = untrusted_sources
    cascade.knobs_ignored = knobs_ignored                # [(message, source)] -> `check` / `!`
    cascade.os_sources = layers.dict_section_sources(layer_list, 'os')
    drvs = layers.merge_dict_section(knob_layers, 'drivers', layers.ALL_ROLES)
    cascade.driver_specs = drvs                      # raw `drivers:` blocks (routecheck lints them)
    cascade.driver_sources = layers.dict_section_sources(layer_list, 'drivers')
    # FORGIVING = any file of a plugin's checkout (its data files AND what they include), so a bad
    # definition anywhere in a plugin is skipped with a warning, never a brick (B4 / routing-04)
    _trees = {layers._plugin_tree(_pf(p)[0]) for p in plugin_files}
    forgiving = _ForgivingPaths(_trees)
    cascade.driver_gates = _driver_gates(drvs, cascade.driver_sources, forgiving, warnings_out)
    from . import routecheck
    fingerprint = _stack_fingerprint(layer_list, untrusted_sources) if validate else None
    check = validate and fingerprint not in _VALIDATED      # already validated: same files, same trust
    clean = True
    components = {}
    for name, chain in layers.collect_named(layer_list, 'components').items():
        # Components merge ADDITIVELY across layers (union of bindings, see _merge_component_chain)
        # rather than replace-per-name: a plugin/user layer can ADD an install method or override
        # one binding without restating the rest. src = the top (amending) layer, for provenance.
        # A malformed / ambiguous component from a PLUGIN file is skipped (a pick that names it
        # then surfaces as a resilient error row) — never fatal.
        # From the repo or your own config it stays a loud, attributed error.
        typos = sorted({s for _i, v, s in chain if _not_a_map(v) and os.path.normpath(s) in forgiving})
        if typos:                                    # a plugin's `foo: bar`: that layer is left out, the
            if warnings_out is not None:             # rest of `foo` (the repo's, say) stands (routing-25)
                warnings_out.append(f'component "{name}": ignored {", ".join(typos)} for it — a component '
                                    f'is a map, not a scalar')
            chain = [c for c in chain if not (_not_a_map(c[1]) and os.path.normpath(c[2]) in forgiving)]
            if not chain:
                continue
        src = chain[-1][2]
        try:
            comp = Component(name, _merge_component_chain(name, [(v, s) for _i, v, s in chain]), checked=True)
            if check:
                routecheck.check_component(name, comp, cascade)
        except ConfigsysError as e:
            clean = False
            if os.path.normpath(src) in forgiving:
                if warnings_out is not None:
                    warnings_out.append(f'skipped component "{name}" ({src}): {e}')
                continue
            # the top layer is yours/the repo's — but if a PLUGIN contributed to the component, the
            # fault may be the plugin's: rebuild it without the plugins' parts and keep that, with a
            # warning naming them (a plugin can't brick your config through a shared component)
            mine = [(v, s) for _i, v, s in chain if os.path.normpath(s) not in forgiving]
            if len(mine) != len(chain):
                try:
                    comp = Component(name, _merge_component_chain(name, mine), checked=True)
                    if validate:
                        routecheck.check_component(name, comp, cascade)
                except ConfigsysError:
                    raise ConfigError(f'{src}: {e}')
                if warnings_out is not None:
                    dropped = sorted({s for _i, _v, s in chain if os.path.normpath(s) in forgiving})
                    warnings_out.append(f'component "{name}": ignored the plugin layer(s) '
                                        f'{", ".join(dropped)} for it — {e}')
            else:
                raise ConfigError(f'{src}: {e}')
        comp.source = src
        comp.shadows = len(chain) > 1
        components[name] = comp

    drivers = {name: cap_names(spec.get('requires') if isinstance(spec, dict) else None)
               for name, spec in drvs.items()}
    # a driver block's `standing: never-auto` marks EVERY binding of
    # that via as valid+listed but never the auto-default (see resolve._select). Ships on snap; a
    # user's primary plugin (or any plugin) can add flatpak etc. via the same overlaid `drivers:`.
    never_auto_drivers = frozenset(name for name, spec in drvs.items()
                               if isinstance(spec, dict) and _standing(spec) == NEVER_AUTO)
    cascade.never_auto_drivers = never_auto_drivers          # so routecheck.validate mirrors resolve._select
    _apply_version_floors(components, layers.merge_version_floors(layer_list),
                          {os.path.normpath(L.path): i for i, L in enumerate(layer_list)})
    if check and clean and fingerprint is not None:
        _VALIDATED.add(fingerprint)
    return Loaded(cascade, components, drivers, never_auto_drivers)


# What an ordinary (non-primary) plugin may NOT set on an os block / driver a lower layer already
# defined: they are preference — your `driver-preference:` setting ranks behind an os block's list,
# and a driver's `standing:` / `when:` act like `disabled-drivers:` — and a plugin doesn't set your
# machine's preferences (the uniform layer rule). On a block the plugin DEFINES they count.
_PLUGIN_KNOBS = {'os': ('driver-preference',), 'drivers': ('standing', 'when')}


def _plugin_knobs_ignored(layer_list, plugin_files):
    '''(layers, [(message, source)]): `layer_list` with an ordinary plugin's _PLUGIN_KNOBS removed
    from every os / drivers entry whose name a lower layer outside that plugin already defined
    (review-2026-11-2 §7.12) — copies, the stack itself is left alone — and a warning per key
    dropped. A plugin's own includes count as the plugin; the primary and your top config keep
    theirs.'''
    trees = set()
    for entry in plugin_files:
        path, role = _pf(entry)
        tree = layers._plugin_tree(path)
        if role == 'plugin' and os.path.exists(os.path.join(tree, 'plugin.hu')):
            trees.add(tree)

    def owner(lyr):                                  # the ordinary plugin a layer belongs to, or None
        if lyr.role == 'plugin':
            return layers._plugin_tree(lyr.path)
        if lyr.role == 'include':
            return next((t for t in trees if layers._inside(lyr.path, t)), None)
        return None

    out, ignored, defined = [], [], {sec: {} for sec in _PLUGIN_KNOBS}   # sec -> {name: owners}
    for lyr in layer_list:
        own = owner(lyr)
        data = lyr.data
        for sec, keys in _PLUGIN_KNOBS.items():
            entries = lyr.data.get(sec)
            if not isinstance(entries, dict):
                continue
            if own is not None:
                for name, spec in entries.items():
                    hit = [k for k in keys if isinstance(spec, dict) and k in spec]
                    if not hit or not (defined[sec].get(name, set()) - {own}):
                        continue                     # nothing to drop / the plugin defines it
                    if data is lyr.data:
                        data = dict(lyr.data)
                    if data[sec] is entries:
                        data[sec] = dict(entries)
                    data[sec][name] = {k: v for k, v in spec.items() if k not in hit}
                    for k in hit:
                        what = f'os: {{ {name}: {{ {k}: … }} }}' if sec == 'os' else \
                               f'drivers: {{ {name}: {{ {k}: … }} }}'
                        ignored.append((f'`{what}` is ignored — a plugin sets preference only on an '
                                        f'{"os block" if sec == "os" else "driver"} it defines '
                                        f'({name!r} comes from a lower layer); set it in your config '
                                        f'or your primary', lyr.path))
            for name in entries:
                defined[sec].setdefault(name, set()).add(own)
        out.append(lyr if data is lyr.data else layers.Layer(lyr.path, lyr.role, data))
    return out, ignored


class _ForgivingPaths:
    '''`path in forgiving` — True for any file inside one of the plugin checkouts.'''

    def __init__(self, trees):
        self.trees = [os.path.realpath(t) for t in trees if t]

    def __contains__(self, path):
        rp = os.path.realpath(str(path))
        return any(rp == t or rp.startswith(t.rstrip(os.sep) + os.sep) for t in self.trees)


def _driver_gates(drvs, sources, forgiving, warnings_out=None):
    '''{driver: (when-text, Predicate)} for every merged `drivers:` block carrying a `when:` — the
    driver-wide VALIDITY gate (e.g. `brew: { when: "glibc_linux" }`: Linuxbrew bottles are glibc
    builds). A malformed gate from a plugin file is dropped with a warning (never bricks the rest);
    from the repo or your own config it is a loud, attributed ConfigError.'''
    gates = {}
    for name, spec in drvs.items():
        if not isinstance(spec, dict) or spec.get('when') is None:
            continue
        text = str(spec['when']).strip()
        try:
            gates[name] = (text, predicate.parse(text))
        except predicate.PredicateError as e:
            src = sources.get(name) or 'routes'
            if src and os.path.normpath(src) in forgiving:
                if warnings_out is not None:
                    warnings_out.append(f'{src}: driver {name!r}: bad `when:` gate ignored — {e}')
                continue
            raise ConfigError(f'{src}: driver {name!r}: bad `when:` — {e}')
    return gates


def _apply_version_floors(components, floors, rank):
    '''Patch merged `version-floors` {component: {cap: (constraint, layer index)}} onto the built
    components: SET the floor wherever the component ALREADY requires the cap (its component-level
    `requires`, and any binding that requires it). A floor for a cap the component doesn't require
    is IGNORED, so it never creates a requirement. Against a floor written inline it follows LAYER
    PRECEDENCE, tighter or looser alike (the user manages): the patch replaces it unless the
    `requires:` that wrote it — the component's (`comp.requires_source`) or the binding's
    (`b.source`) — sits in a HIGHER layer than the patch (`rank`: layer path -> index); a same-layer
    patch replaces it too. A bare requirement has no floor to defend, so any layer's patch sets it
    (a floors plugin sorted below the recipes it serves). It acts like an authored floor at either
    level: the resolver selects (or fails) a provider of that cap by version, exactly as for
    `requires: { cap: ">=N" }` written in place (routing-model §11; B15).'''
    def _layer(src):
        return rank.get(os.path.normpath(src), -1) if src else -1
    for cname, cap_map in floors.items():
        comp = components.get(cname)
        if comp is None or not isinstance(cap_map, dict):
            continue
        for cap, (con, at) in cap_map.items():
            con = str(con)
            targets = [(comp.req_versions, comp.requires_source)] if cap in comp.requires else []
            targets += [(b.req_versions, b.source) for b in comp.bindings
                        if cap in cap_names(b.details.get('requires'))]
            for cons, src in targets:
                if cap not in cons or _layer(src) <= at:
                    cons[cap] = con


_FACET_CACHE = {}


def clear_facet_cache():
    '''Forget every probed facet value, so the next Resolver re-runs the `detect:` probes — `configsys
    refresh` (a new GPU / CUDA since the last run) and the test suite.'''
    _FACET_CACHE.clear()


def _facet_value(raw, kind):
    '''A config-declared facet value as the override string. A humon LIST is accepted for a
    categorical facet (`gpu: [ nvidia amd ]` = both tags — joined, the same as `gpu: "nvidia amd"`);
    for a version facet a list takes its first item. A map can't be a value -> None (unset).'''
    if isinstance(raw, dict):
        return None
    if isinstance(raw, (list, tuple)):
        items = [str(x).strip() for x in raw if x is not None and not isinstance(x, (dict, list))]
        items = [x for x in items if x]
        if not items:
            return None
        return ' '.join(items) if kind == 'categorical' else items[0]
    return None if raw is None else str(raw)


def detect_facets(specs, env=None, run=None, overrides=None):
    '''Probe the declared `facets:` and return (facets_cat {ns: frozenset(tags)}, facets_ver
    {name: version}). A facet's value is, in precedence order: a `CONFIGSYS_FACET_<name>` ENV var;
    then a config `overrides` entry (the user's declared machine fact — so "detected OR declared" is
    ONE mechanism, key to bootstrap: on a box without CUDA yet, `facets: { cuda: 12 }` in the config
    states the target); then the `detect:` PROBE, classified per `kind` — `categorical` matches each
    `match:` regex against the output (a machine may match several tags); `version` pulls
    `version-re`'s first group. Read-only and resilient: any probe failure / no value leaves the
    facet ABSENT (a `when:` over it is then simply false). Cached per (specs, env+config overrides)
    so repeated Resolver builds don't re-probe. `run(cmd)->stdout` is injectable for tests.'''
    import json
    import os
    import re
    import subprocess
    env = env if env is not None else os.environ
    overrides = overrides or {}
    key = json.dumps({'specs': specs, 'cfg': overrides,
                      'ov': {k: v for k, v in env.items()
                             if k.startswith('CONFIGSYS_FACET_')}}, sort_keys=True)
    if run is None and key in _FACET_CACHE:
        return _FACET_CACHE[key]

    def _run(cmd):
        if run is not None:
            return run(cmd)
        try:
            return subprocess.run(str(cmd), shell=True, capture_output=True, text=True,
                                  timeout=15).stdout or ''
        except (OSError, subprocess.SubprocessError):
            return ''

    cat, ver = {}, {}
    for name, spec in (specs or {}).items():
        if not isinstance(spec, dict):
            continue                                  # malformed spec (load warns + drops these)
        override = env.get(f'CONFIGSYS_FACET_{name}')
        if override is None and name in overrides:
            override = _facet_value(overrides[name], spec.get('kind'))   # config-declared (env wins)
        if spec.get('kind') == 'categorical':
            if override is not None:
                tags = frozenset(t for t in re.split(r'[,\s]+', override) if t)
            else:
                out = _run(spec['detect']) if spec.get('detect') else ''
                tags = frozenset(tag for tag, pat in (spec.get('match') or {}).items()
                                 if pat and re.search(str(pat), out))
            if tags:
                cat[name] = tags
        elif spec.get('kind') == 'version':
            v = override
            if v is None and spec.get('detect'):
                m = re.search(str(spec.get('version-re') or r'([0-9]+(?:\.[0-9]+)*)'),
                              _run(spec['detect']))
                v = m.group(1) if m else None
            if v:
                ver[name] = v
    if run is None:
        _FACET_CACHE[key] = (cat, ver)
    return cat, ver


# The machine's SELECTION POLICY — everything besides the OS context that decides which method wins:
# your pins, the component-names patches, driver-preference, the never-auto drivers and the disabled
# ones. Resolver.policy hands it out whole, so a caller resolving or selecting can't forget one of
# them (review-2026-11-2 D6 / routing-18: request coverage resolved without four of the five).
SelectionPolicy = namedtuple('SelectionPolicy', 'pins overrides preference never_auto_drivers disabled')

# The outcome of one component's method selection: the winning binding, every candidate here, and the
# rule that decided (resolve._select's: 'only method here' — also a binding-pin's single match —
# 'only ordinary method here', 'most-specific when:', 'standing:', 'driver-preference').
Selection = namedtuple('Selection', 'binding candidates rule')


class Resolver:
    '''The app-facing resolver: load the layer stack once, then resolve component names (the
    picks, or an op's names) to `{key: ResolvedComponent}` for this machine's context (OS block +
    version + cpu) under its selection policy (`policy`). `resolve_with_roots` also returns the
    directly-bound unit keys the app applies
    an op to (dependency installs are folded in by planning.expand_plan).'''

    def __init__(self, routes_path, block, version=None, cpu=None, pins=None,
                 overrides_path=None, plugin_files=(), preference=None,
                 disabled=None, command_trust=None, home=None):
        self.load_warnings = []       # skipped files/components (for diagnostics)
        self.layers = []              # expanded layer stack low→high (for `-v` reporting)
        self.cascade, self.components, self.drivers, self.never_auto_drivers = load(
            routes_path, overrides_path, plugin_files,
            warnings_out=self.load_warnings, layers_out=self.layers, command_trust=command_trust,
            home=home)
        # probe declared facets (gpu vendor, cuda version, …) so `when:` can gate on hardware /
        # environment; cached, read-only, resilient. No `facets:` declared -> a no-op. A `facets:`
        # value-map in the user config declares facts (e.g. `facets: { cuda: 12 }` on a box without
        # CUDA yet) — it overrides the probe, env (CONFIGSYS_FACET_*) overrides both.
        if self.cascade.facet_specs:
            ov = layers.read_setting(overrides_path, 'facets') if overrides_path else None
            self.cascade.facets_cat, self.cascade.facets_ver = detect_facets(
                self.cascade.facet_specs, overrides=ov if isinstance(ov, dict) else None)
        # per-driver package-name patches for existing components (a plugin OS supplying its
        # own names / dropping absent ones) — overlaid across the whole layer stack.
        self.overrides = layers.merge_name_overrides(self.layers)
        self.block = block
        self.version = version
        self.cpu = cpu
        self.pins = pins or {}
        self.tighten_pins = {}                       # the last resilient resolve's auto-tighten pins
        self.preference = preference or None   # driver-preference order; None = built-in default
        self.disabled = frozenset(disabled or ())   # vias disabled on this machine (`disabled-drivers:`)
        self._dep_index = None                       # lazy cap -> {dependent components} reverse index
        self.dropped_soft_pins = {}                  # {pin key: reason} soft pins the last resilient resolve dropped
        self.skipped_parts = {}                      # {bundle: [(part, why)]} from the last resilient resolve
        self.provider_rules = {}                     # {cap: deciding rule} from the last resilient resolve

    @property
    def policy(self):
        return SelectionPolicy(self.pins, self.overrides, self.preference, self.never_auto_drivers,
                               self.disabled)

    def select(self, name, *, pins=None, context=None):
        '''-> Selection for component `name` (or a Component) on this machine: the method resolution
        would choose for it under this machine's policy — `pins` replaces your pins (`unpinned(name)`
        asks what the auto-default would be), `context` a context() you already hold. Raises
        ResolveError when nothing is valid here or the choice is undecidable.'''
        from .resolve import ResolveError, _select
        comp = self.components.get(name) if isinstance(name, str) else name
        if comp is None:
            raise ResolveError(f'unknown component: {name}')
        return Selection(*_select(comp, self.cascade, context or self.context(),
                                  self.pins if pins is None else pins, self.preference,
                                  self.never_auto_drivers))

    def unpinned(self, name):
        '''Your pins without `name`'s own — what the auto-default for `name` follows.'''
        return {k: v for k, v in self.pins.items() if k != name}

    def resolve_at(self, names, block, version=None):
        '''Raw units for `names` resolved on ANOTHER OS (`block`, `version`) under THIS machine's whole
        selection policy — the request/report coverage matrix. Raises ResolveError.'''
        from .resolve import resolve
        p = self.policy
        return resolve(list(names), self.cascade, self.components, self.drivers, block, version,
                       self.cpu, p.pins, p.overrides, p.preference, p.never_auto_drivers, p.disabled)

    @property
    def cascade_names(self):
        '''The OS lineage leaf-first (e.g. rhel -> redhat -> linux), for display/tests.'''
        return self.cascade.lineage(self.block)

    def context(self, block=None, version=None, disabled=None):
        '''This machine's predicate context — block + version + cpu + the DISABLED vias. Every caller
        that evaluates `when:` / lists candidate bindings must use this (not a hand-built
        `cascade.context(block, version, cpu)`), or a `disabled-drivers:` via leaks back in — e.g.
        detection would soft-pin a disabled driver, producing a phantom "no binding … pinned to …"
        error row for a component that resolved fine. It also carries every driver gate — the
        explicit `drivers:` `when:` ones and the DERIVED ones (a driver whose own `requires:` can't be
        met here under your pins; resolve.gated_context) — so `where`, the picker and detection see
        exactly the candidates resolution does. `block`/`version`/`disabled` default to this
        machine's (pass `disabled=()` to ask what WOULD be valid with no driver disabled). The derived
        gates read the same HARD pins resolution does: yours over the last resolve's auto-tighten
        floor pins (`tighten_pins`), so a floor pin that opens a driver opens it here too.'''
        from .resolve import gated_context
        return gated_context(self.cascade, self.components, self.drivers,
                             block or self.block, self.version if block is None else version,
                             self.cpu, self.disabled if disabled is None else disabled,
                             {**self.tighten_pins, **self.pins},
                             self.overrides, self.preference, self.never_auto_drivers)

    def _resolve(self, names):
        from .resolve import resolve_roots
        return resolve_roots(list(names), self.cascade, self.components, self.drivers,
                             self.block, self.version, self.cpu, self.pins, self.overrides,
                             self.preference, self.never_auto_drivers, self.disabled)

    def resolve_names(self, names):
        from .adapt import to_resolved_components
        return to_resolved_components(self._resolve(names)[0])

    def resolve_resilient(self, names, extra_pins=None, soft_pins=None, *, record=False, out=None,
                          disabled=None):
        '''-> ({key: ResolvedComponent}, {name: error_message}). Tolerant: a requested name
        that can't route here is reported, not fatal (for inspect/TUI over this machine's picks).
        Precedence (routing-model §10): YOUR config pins > `extra_pins` (auto-tighten floor pins) >
        `soft_pins` (the detection tier) > the default. A user pin always wins — when it keeps a
        method that fails a floor auto-tighten would have fixed, flooradvise.advise says so (the `!`
        page) instead of overriding you. Detected pins are SOFT: one that can't be honored here (it
        fails a version constraint, or names a method/provider not valid here) is dropped for this
        resolution — never an error; the dropped ones are recorded in `self.dropped_soft_pins`.
        Applied to THIS resolve only (the Resolver's own pins aren't mutated; the extra pins are kept as
        `tighten_pins` so context() gates drivers the way this resolve did).

        Those per-resolve outputs (tighten_pins / dropped_soft_pins / provider_rules / skipped_parts)
        are written onto this shared Resolver only with `record=True` — the load pipeline's resolve,
        whose state `where`, context() and the `!` page describe. Every other resolve (a TUI overlay
        thread, a diagnostics helper) passes nothing and leaves them alone (B16 / tui-core-06); `out`
        (a dict) receives them either way. `disabled` replaces the machine's disabled drivers for this
        resolve only (`disabled=()`: what would route with none disabled).'''
        from .adapt import to_resolved_components
        from .resolve import resolve_resilient
        soft_pins, extra_pins = dict(soft_pins or {}), dict(extra_pins or {})
        if record:
            self.tighten_pins = extra_pins             # context() gates drivers under these too
        pins = ({**soft_pins, **extra_pins, **self.pins}
                if (extra_pins or soft_pins) else self.pins)
        soft = frozenset(k for k in soft_pins if k not in self.pins and k not in extra_pins)
        dropped, rules, skipped, kinds = {}, {}, {}, {}
        units, errors = resolve_resilient(list(names), self.cascade, self.components,
                                          self.drivers, self.block, self.version,
                                          self.cpu, pins, self.overrides, self.preference,
                                          self.never_auto_drivers,
                                          self.disabled if disabled is None else frozenset(disabled),
                                          soft=soft, dropped_out=dropped,
                                          provider_rules_out=rules, skipped_parts_out=skipped,
                                          kinds_out=kinds)
        if record:
            self.dropped_soft_pins = dropped
            self.skipped_parts = skipped    # {bundle: [(part, why)]} parts with no route here
            self.provider_rules = rules     # {cap: rule that picked its auto provider} (for `where`)
        if out is not None:
            out.update(tighten_pins=extra_pins, dropped_soft_pins=dropped, skipped_parts=skipped,
                       provider_rules=rules, error_kinds=kinds)   # {name: ResolveError kind}
        return to_resolved_components(units), errors

    def resolve_with_roots(self, names, extra_pins=None, soft_pins=None, *, out=None):
        '''-> ({key: ResolvedComponent}, root keys) for the named components. `extra_pins` (auto-
        tighten floor pins) and `soft_pins` (the detection tier) layer under YOUR pins exactly as in
        resolve_resilient, so a CLI op on an adopted install targets that install (B1). Like any
        non-pipeline resolve it leaves the Resolver's recorded state alone; `out` (a dict) receives
        the dropped soft pins.'''
        from .adapt import to_resolved_components
        if not (extra_pins or soft_pins):
            units, roots = self._resolve(names)
            return to_resolved_components(units), roots
        from .resolve import resolve_roots
        soft_pins, extra_pins = dict(soft_pins or {}), dict(extra_pins or {})
        pins = {**soft_pins, **extra_pins, **self.pins}
        soft = frozenset(k for k in soft_pins if k not in self.pins and k not in extra_pins)
        dropped = {}
        units, roots = resolve_roots(list(names), self.cascade, self.components, self.drivers,
                                     self.block, self.version, self.cpu, pins, self.overrides,
                                     self.preference, self.never_auto_drivers, self.disabled,
                                     soft=soft, dropped_out=dropped)
        if out is not None:
            out.update(dropped_soft_pins=dropped)
        return to_resolved_components(units), roots

    def candidates(self, name):
        '''The install methods for `name` -> [{via, when, default, pinned, auto, available}] in binding
        order: the CANDIDATES on this machine (`when:`-true, cpu-covered, not disabled or gated —
        resolve.candidate_bindings) — the honest "what can I install
        here" set that feeds `where`, the pin CLI, and the method picker (`available` is always
        True; kept for the row shape). `default` is the one that resolves now (a pin, else the
        preference-picked binding); `pinned` flags the via a binding-pin names; `auto` the one that
        would resolve with no pin (== default when unpinned). [] if the component
        is unknown / removed / unroutable here.'''
        from .resolve import candidate_bindings, via_representatives, ResolveError
        comp = self.components.get(name)
        if comp is None or not comp.bindings:
            return []
        ctx = self.context()
        valid = candidate_bindings(comp, self.cascade, ctx)      # candidates here (ignore pin filter)
        valid_vias = {b.via for b in valid}
        if not valid:
            return []
        # The picker and pins choose a VIA (1:1 with a driver), not an individual binding — the
        # resolver auto-picks the most-specific binding within a via. So collapse multiple
        # same-via candidates (e.g. fastfetch's `when: debian` .deb binding subsumed by its bare
        # `via: native`) to the one that resolves for that via — one row per real choice.
        reps = via_representatives(valid, self.cascade)
        try:
            winner = self.select(comp, context=ctx).binding
        except ResolveError:
            winner = None
        from .resolve import binding_pin
        pinned_via = binding_pin(self.pins, name)
        auto = winner
        if pinned_via is not None:                 # what UNPINNING would give you (B16 / tui-core-05)
            try:
                auto = self.select(comp, pins=self.unpinned(name), context=ctx).binding
            except ResolveError:
                auto = None
        auto_via = auto.via if auto is not None else None
        return [{'via': b.via, 'when': b.when, 'default': b is winner,
                 'pinned': pinned_via == b.via, 'auto': b.via == auto_via,
                 'available': b.via in valid_vias} for b in reps]

    def dependents(self, name):
        '''What DEPENDS ON `name` -> a list of `(dependent, is_driver)` pairs, components first (both
        groups sorted). A dependent names a capability `name` provides in its `requires:`, `suggests:`,
        or `parts:` — at the component level OR in ANY binding (every install method, regardless of
        `when:`/machine-legality — this feeds the machine-agnostic Profiles screen). A component
        provides its own name as a capability, so a bare `requires: <name>` counts; a versioned-
        capability provider (e.g. `python3.13` provides `python3`) also surfaces the consumers of that
        shared capability. `parts:` is authored on the `via: parts` binding (a bundle = the union of
        its parts, often `when:`-gated per OS), so a component that lists `name` among a bundle's parts
        counts too. DRIVERS count as well (`is_driver=True`): a driver's inherent `requires:` (e.g.
        appImage -> libfuse2) means `name` is needed by every install THROUGH that driver. `[]` for an
        unknown component.'''
        comp = self.components.get(name)
        if comp is None:
            return []
        caps = set(comp.provides) | {name}          # what `name` can satisfy
        # reverse index (cap -> {components that depend on it}) built ONCE — components are immutable
        # after load, so a full rescan per call (this is called per catalog cursor move in the TUI, and
        # per orphan) was pure waste.
        if self._dep_index is None:
            idx = {}
            for other, c in self.components.items():
                edges = set(c.requires) | set(c.suggests) | set(c.parts)   # component-level edges
                for b in c.bindings:                                      # + every binding's edges
                    edges |= set(cap_names(b.details.get('requires')))
                    edges |= set(cap_names(b.details.get('suggests')))
                    edges |= set(as_list(b.details.get('parts')))        # a `via: parts` bundle's members
                for cap in edges:
                    idx.setdefault(cap, set()).add(other)
            self._dep_index = idx
        comps = set().union(*(self._dep_index.get(cap, ()) for cap in caps)) if caps else set()
        comps.discard(name)
        drivers = [d for d, reqs in self.drivers.items() if caps & set(reqs)]
        return [(n, False) for n in sorted(comps)] + [(n, True) for n in sorted(drivers)]
