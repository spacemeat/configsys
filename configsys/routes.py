'''routes.py — load routes.hu into an OS cascade + components, and the app-facing Resolver.

Turns humon nodes into small dataclasses the resolver walks (OsCascade / Component /
Binding), validates the file (ambiguity check), and exposes `Resolver`: the object the app
holds to turn a profile's component names into the `{key: ResolvedComponent}` closure for
this machine's context. Resolution itself lives in resolve.py; the RC marshalling in adapt.py.
'''

import os

from . import layers, predicate
from .errors import ConfigError, ConfigsysError
from .resolve import cap_constraints, cap_names


class Binding:
    def __init__(self, spec):
        spec = dict(spec)
        self.source = spec.pop('__source__', None)   # layer that contributed this binding (merge)
        spec.pop('drop', None)                        # a merge directive, never install data
        self.when = spec.pop('when', None)
        self.pred = predicate.parse(self.when)
        self.via = spec.pop('via', None)
        if self.via is None:
            raise ValueError(f'binding without `via`: {spec}')
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
                             'description'})
# the non-`install` fields, which merge with inheritance (a layer that omits one keeps the lower).
_COMPONENT_FIELDS = ('provides', 'requires', 'suggests', 'parts', 'standing', 'description')


def _check_component_keys(name, spec):
    unknown = set(spec) - _COMPONENT_KEYS
    if unknown:
        hint = ''
        if 'dotfiles' in unknown:  # the removed inline-node construct
            hint = '; config is a required `<name>-dotfiles` component now, not a `dotfiles:` field'
        raise ConfigError(
            f'component {name!r}: unknown key(s) {sorted(unknown)}; '
            f'valid keys are {sorted(_COMPONENT_KEYS)}{hint}')


def _binding_identity(b):
    '''A binding's merge identity: (via, when-as-written). A higher-layer binding with the same
    identity OVERRIDES the lower; a `drop:` binding with this identity retracts it.'''
    return (b.get('via'), None if b.get('when') is None else str(b.get('when')).strip())


def _merge_component_chain(name, chain):
    '''Merge a component's per-layer definitions (ascending precedence) into one spec, ADDITIVELY:
    - an empty spec `{}` is a TOMBSTONE — it clears everything accumulated so far (whole-component
      removal, the unchanged `{}` convention);
    - `install:` bindings UNION keyed by (via, when): a higher binding with the same identity
      overrides the lower, a `drop:` binding retracts the matching inherited one;
    - the other fields (provides/requires/suggests/parts/standing) override with inheritance.
    Each surviving binding is tagged `__source__` with the layer that contributed it (so a dotfiles
    binding's content root, and provenance, follow the defining layer even across an amend).'''
    fields, bindings = {}, {}          # bindings: (via, when) -> spec dict (insertion order kept)
    for val, src in chain:
        spec = val if isinstance(val, dict) else {}
        _check_component_keys(name, spec)
        if not spec:                   # {} tombstone: forget everything below, start fresh
            fields, bindings = {}, {}
            continue
        for k in _COMPONENT_FIELDS:
            if k in spec:
                fields[k] = spec[k]
        for b in (spec.get('install') or []):
            ident = _binding_identity(b)
            if _truthy(b.get('drop')):
                bindings.pop(ident, None)
                continue
            bindings[ident] = {**b, '__source__': src}
    return {**fields, 'install': list(bindings.values())}


class Component:
    def __init__(self, name, spec):
        self.source = None       # file this definition came from (provenance for `where`)
        self.shadows = False     # True if more than one layer contributed to this component
        _check_component_keys(name, spec)
        self.name = name
        # provides/requires/suggests carry NAMES (resolver closes on these, unchanged) plus, for
        # any versioned `{ cap: constraint }` entries, a parallel constraint map (stage 2): the
        # component-level version floors, read by the sweep + floor-aware resolution.
        self.provides = cap_names(spec.get('provides'))
        self.prov_versions = cap_constraints(spec.get('provides'))
        self.requires = cap_names(spec.get('requires'))
        self.req_versions = cap_constraints(spec.get('requires'))
        self.suggests = cap_names(spec.get('suggests'))   # soft deps: pulled if resolvable, else skipped
        self.parts = _as_list(spec.get('parts'))
        # a `standing: never-auto` provider satisfies a `requires:` only when explicitly wanted /
        # provider-pinned / version-constrained — NEVER auto-pulled to close someone else's
        # requirement. For best-effort/caveated providers (e.g. gcompat, a glibc shim) or the
        # non-default of a versioned pair. See resolve.py `_satisfy`.
        from .resolve import NEVER_AUTO, _standing
        self.opt_in = _standing(spec) == NEVER_AUTO
        # optional one-line human description (names can be esoteric); shown in the TUI. Empty if
        # unset — populated incrementally in routes.hu/plugins.
        self.description = str(spec.get('description') or '')
        self.bindings = [Binding(b) for b in (spec.get('install') or [])]


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _truthy(v):
    return str(v).lower() in ('true', 'yes', '1')


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

    def provides(self, block):
        '''Capabilities baseline in this environment (union over the lineage's blocks).'''
        caps = set()
        for n in self.lineage(block):
            caps.update(_as_list((self.blocks[n] or {}).get('provides')))
        return caps

    def lineage(self, name):
        '''Leaf-first chain following `using` to the root.'''
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

    def is_descendant(self, x, y):
        '''True if y is ancestor-or-self of x (x's subtree ⊆ y's subtree).'''
        return y in self.lineage(x)

    def context(self, block, version=None, cpu=None, disabled=()):
        return predicate.Context(self.lineage(block), version, cpu, self.scale_roots,
                                 facets_cat=self.facets_cat, facets_ver=self.facets_ver,
                                 disabled=disabled)


def _pf(entry):
    '''Normalize a plugin_files entry to (path, role). Accepts a bare path (defaults to the
    `plugin` role — used by tests/older callers) or an already-roled (path, role) tuple.'''
    if isinstance(entry, (tuple, list)):
        return (entry[0], entry[1] if len(entry) > 1 else 'plugin')
    return (entry, 'plugin')


def load(path, overrides_path=None, plugin_files=(), validate=True,
         warnings_out=None, layers_out=None):
    '''-> (OsCascade, {component_name: Component}, {driver: [required caps]}).

    Layer stack lowest-first: routes.hu (repo) < plugin data files < the user's config, each with
    its `include:` graph expanded. Components merge PER NAME ADDITIVELY (union of install bindings
    by (via, when) identity; higher layer overrides a matching binding, `drop:` retracts one, `{}`
    removes the whole component — see _merge_component_chain); os/drivers come from repo + plugins
    (a plugin may add a derivative-distro os block). A malformed plugin file is skipped (never
    bricks the rest). validate=True rejects an ambiguous set. If a list is passed as `warnings_out`,
    skipped files/components are appended to it (for the diagnostics view) — the return value is
    unchanged so existing callers are unaffected.
    '''
    roots = [(path, 'repo')]
    roots += [_pf(p) for p in plugin_files]          # (path, role): 'primary' or 'plugin'
    if overrides_path is not None:
        roots.append((overrides_path, 'user'))
    layer_list, _warnings = layers.expand_tolerant(roots, {'plugin', 'primary'})
    if warnings_out is not None:
        warnings_out.extend(_warnings)
    if layers_out is not None:                       # (path, role) low→high, for `-v` reporting
        layers_out.extend(layer_list)

    cascade = OsCascade(layers.merge_dict_section(layer_list, 'os', ('repo', 'plugin', 'primary')),
                        layers.merge_dict_section(layer_list, 'facets', ('repo', 'plugin', 'primary')))
    forgiving = {os.path.normpath(_pf(p)[0]) for p in plugin_files}
    from . import routecheck
    components = {}
    for name, chain in layers.collect_named(layer_list, 'components').items():
        # Components merge ADDITIVELY across layers (union of bindings, see _merge_component_chain)
        # rather than replace-per-name: a plugin/user layer can ADD an install method or override
        # one binding without restating the rest. src = the top (amending) layer, for provenance.
        # A malformed / ambiguous component from a DISCOVERED or PLUGIN file is skipped (the
        # profile that referenced it then surfaces as a resilient error row) — never fatal.
        # From the repo or your own config it stays a loud, attributed error.
        src = chain[-1][2]
        try:
            comp = Component(name, _merge_component_chain(name, [(v, s) for _i, v, s in chain]))
            if validate:
                routecheck.check_component(name, comp, cascade)
        except ConfigsysError as e:
            if os.path.normpath(src) in forgiving:
                if warnings_out is not None:
                    warnings_out.append(f'skipped component "{name}" ({src}): {e}')
                continue
            raise ConfigError(f'{src}: {e}')
        comp.source = src
        comp.shadows = len(chain) > 1
        components[name] = comp

    drvs = layers.merge_dict_section(layer_list, 'drivers', ('repo', 'plugin', 'primary'))
    drivers = {name: cap_names((spec or {}).get('requires')) for name, spec in drvs.items()}
    # a driver block's `standing: never-auto` marks EVERY binding of
    # that via as valid+listed but never the auto-default (see resolve._select). Ships on snap; a
    # user's primary plugin (or any plugin) can add flatpak etc. via the same overlaid `drivers:`.
    from .resolve import NEVER_AUTO, _standing
    candidate_only = frozenset(name for name, spec in drvs.items()
                               if _standing(spec or {}) == NEVER_AUTO)
    _apply_version_floors(components, layers.merge_version_floors(layer_list))
    return cascade, components, drivers, candidate_only


def _apply_version_floors(components, floors):
    '''Patch merged `version-floors` {component: {cap: constraint}} onto the built components: set
    the floor wherever the component ALREADY requires the cap (its component-level `requires`, and
    any binding that requires it). A patch only TIGHTENS an existing requirement — a floor for a cap
    the component doesn't require is IGNORED, so it never creates a requirement and resolution is
    unchanged (only the sweep / advisory read the added version metadata).'''
    for cname, cap_map in floors.items():
        comp = components.get(cname)
        if comp is None or not isinstance(cap_map, dict):
            continue
        for cap, con in cap_map.items():
            con = str(con)
            if cap in comp.requires:
                comp.req_versions[cap] = con
            for b in comp.bindings:
                if cap in cap_names(b.details.get('requires')):
                    b.req_versions[cap] = con


_FACET_CACHE = {}


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
        spec = spec or {}
        override = env.get(f'CONFIGSYS_FACET_{name}')
        if override is None and name in overrides:
            override = str(overrides[name])           # config-declared value (env still wins)
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


class Resolver:
    '''The app-facing resolver: load routes.hu once, then resolve a profile's component
    names to `{key: ResolvedComponent}` for this machine's context (OS block + version +
    cpu). `resolve_with_roots` also returns the directly-bound unit keys the app applies
    an op to (dependency installs are folded in by planning.expand_plan).'''

    def __init__(self, routes_path, block, version=None, cpu=None, pins=None,
                 overrides_path=None, plugin_files=(), preference=None,
                 disabled=None):
        self.load_warnings = []       # skipped files/components (for diagnostics)
        self.layers = []              # expanded layer stack low→high (for `-v` reporting)
        self.cascade, self.components, self.drivers, self.candidate_only = load(
            routes_path, overrides_path, plugin_files,
            warnings_out=self.load_warnings, layers_out=self.layers)
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
        self.preference = preference or None   # driver-preference order; None = built-in default
        self.disabled = frozenset(disabled or ())   # vias disabled on this machine (`disabled-drivers:`)

    @property
    def cascade_names(self):
        '''The OS lineage leaf-first (e.g. rhel -> redhat -> linux), for display/tests.'''
        return self.cascade.lineage(self.block)

    def _resolve(self, names):
        from .resolve import resolve_roots
        return resolve_roots(list(names), self.cascade, self.components, self.drivers,
                             self.block, self.version, self.cpu, self.pins, self.overrides,
                             self.preference, self.candidate_only, self.disabled)

    def resolve_names(self, names):
        from .adapt import to_resolved_components
        return to_resolved_components(self._resolve(names)[0])

    def resolve_resilient(self, names, extra_pins=None, soft_pins=None):
        '''-> ({key: ResolvedComponent}, {name: error_message}). Tolerant: a requested name
        that can't route here is reported, not fatal (for inspect/TUI over the active set).
        `extra_pins` (auto-tighten) layer ON TOP of the config pins; `soft_pins` (the detection
        tier) layer BELOW them — so precedence is soft/detected < user pin < extra/tighten. Applied
        to THIS resolve only (the Resolver isn't mutated).'''
        from .adapt import to_resolved_components
        from .resolve import resolve_resilient
        pins = ({**(soft_pins or {}), **self.pins, **(extra_pins or {})}
                if (extra_pins or soft_pins) else self.pins)
        units, errors = resolve_resilient(list(names), self.cascade, self.components,
                                          self.drivers, self.block, self.version,
                                          self.cpu, pins, self.overrides, self.preference,
                                          self.candidate_only, self.disabled)
        return to_resolved_components(units), errors

    def resolve_with_roots(self, names):
        from .adapt import to_resolved_components
        units, roots = self._resolve(names)
        return to_resolved_components(units), roots

    def candidates(self, name, include_unavailable=False):
        '''The install methods for `name` -> [{via, when, default, pinned, available}] in binding
        order. By default only methods VALID on this machine (`when:`-true) are listed — the honest
        "what can I install here" set that feeds `where`, the pin CLI, and the method picker.
        `include_unavailable=True` also lists methods gated out by `when:` (marked `available:
        False`) — for the Profiles screen, where the user may be authoring for OTHER machines and
        wants the whole menu. `default` is the one that resolves now (a pin, else the
        preference-picked binding); `pinned` flags the via a binding-pin names. [] if the component
        is unknown / removed / (when not including unavailable) unroutable here.'''
        from .resolve import candidate_bindings, _select, via_representatives, ResolveError
        comp = self.components.get(name)
        if comp is None or not comp.bindings:
            return []
        ctx = self.cascade.context(self.block, self.version, self.cpu, self.disabled)
        valid = candidate_bindings(comp, self.cascade, ctx)      # `when:`-true here (ignore pin filter)
        valid_vias = {b.via for b in valid}
        if include_unavailable:
            # every distinct via the component defines, valid here or not (first binding per via)
            seen, reps = set(), []
            for b in comp.bindings:
                if b.via not in seen:
                    seen.add(b.via)
                    reps.append(b)
        else:
            if not valid:
                return []
            # The picker and pins choose a VIA (1:1 with a driver), not an individual binding — the
            # resolver auto-picks the most-specific binding within a via. So collapse multiple
            # same-via candidates (e.g. fastfetch's `when: debian` .deb binding subsumed by its bare
            # `via: native`) to the one that resolves for that via — one row per real choice.
            reps = via_representatives(valid, self.cascade)
        try:
            winner = _select(comp, self.cascade, ctx, self.pins, self.preference,
                             self.candidate_only)[0]
        except ResolveError:
            winner = None
        pinned_via = self.pins.get(name)
        return [{'via': b.via, 'when': b.when, 'default': b is winner,
                 'pinned': pinned_via == b.via, 'available': b.via in valid_vias} for b in reps]

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
        comps = []
        for other, c in self.components.items():
            if other == name:
                continue
            edges = set(c.requires) | set(c.suggests) | set(c.parts)   # component-level edges
            for b in c.bindings:                                      # + every binding's edges
                edges |= set(cap_names(b.details.get('requires')))
                edges |= set(cap_names(b.details.get('suggests')))
                edges |= set(_as_list(b.details.get('parts')))        # a `via: parts` bundle's members
            if edges & caps:
                comps.append(other)
        drivers = [d for d, reqs in self.drivers.items() if caps & set(reqs)]
        return [(n, False) for n in sorted(comps)] + [(n, True) for n in sorted(drivers)]
