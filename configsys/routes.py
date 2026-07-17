'''routes.py — load routes.hu into an OS cascade + components, and the app-facing Resolver.

Turns humon nodes into small dataclasses the resolver walks (OsCascade / Component /
Binding), validates the file (ambiguity check), and exposes `Resolver`: the object the app
holds to turn a profile's component names into the `{key: ResolvedComponent}` closure for
this machine's context. Resolution itself lives in resolve.py; the RC marshalling in adapt.py.
'''

from . import layers, predicate
from .errors import ConfigError


class Binding:
    def __init__(self, spec):
        spec = dict(spec)
        self.when = spec.pop('when', None)
        self.pred = predicate.parse(self.when)
        self.via = spec.pop('via', None)
        if self.via is None:
            raise ValueError(f'binding without `via`: {spec}')
        self.details = spec               # everything else (name, app, foreign-arch, ...)


class Component:
    # top-level keys a component may carry; anything else is a typo or a removed construct
    # (e.g. the old inline `dotfiles:` node) and must fail loudly, not vanish silently.
    _KEYS = frozenset({'provides', 'requires', 'parts', 'install'})

    def __init__(self, name, spec):
        self.source = None       # file this definition came from (provenance for `where`)
        self.shadows = False     # True if a user override replaced a same-named repo component
        unknown = set(spec) - self._KEYS
        if unknown:
            hint = ''
            if 'dotfiles' in unknown:  # the removed inline-node construct
                hint = '; config is a required `<name>-dotfiles` component now, not a `dotfiles:` field'
            raise ConfigError(
                f'component {name!r}: unknown key(s) {sorted(unknown)}; '
                f'valid keys are {sorted(self._KEYS)}{hint}')
        self.name = name
        self.provides = _as_list(spec.get('provides'))
        self.requires = _as_list(spec.get('requires'))
        self.parts = _as_list(spec.get('parts'))
        self.bindings = [Binding(b) for b in (spec.get('install') or [])]


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _truthy(v):
    return str(v).lower() in ('true', 'yes', '1')


class OsCascade:
    '''The OS layer: `using` inheritance, the `native` mechanism, scale-roots, and the
    capabilities each environment provides for free.'''

    def __init__(self, os_dict):
        self.blocks = os_dict
        self.scale_roots = {n for n, b in os_dict.items()
                            if isinstance(b, dict) and _truthy(b.get('scale-root'))}

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
        '''The nearest `native:` mechanism walking the lineage (None if none set).'''
        for n in self.lineage(name):
            mech = (self.blocks[n] or {}).get('native')
            if mech:
                return mech
        return None

    def is_descendant(self, x, y):
        '''True if y is ancestor-or-self of x (x's subtree ⊆ y's subtree).'''
        return y in self.lineage(x)

    def context(self, block, version=None, cpu=None):
        return predicate.Context(self.lineage(block), version, cpu, self.scale_roots)


def load(path, overrides_path=None, validate=True):
    '''-> (OsCascade, {component_name: Component}, {mechanism: [required caps]}).

    `path` (routes.hu) is the base repo layer. `overrides_path` (the user's ~/configsys.hu,
    optional) and any files it (or routes.hu) `include:` overlay it: components merge PER NAME
    (later layer wins — redefine wholesale, add, or remove with `{}`), while os/mechanisms stay
    repo-only. With validate=True, an ambiguous merged set is rejected up front (AmbiguityError).
    '''
    roots = [(path, 'repo')]
    if overrides_path is not None:
        roots.append((overrides_path, 'user'))
    layer_list = layers.expand(roots)          # include graphs expanded, cycle-checked

    cascade = OsCascade(layers.repo_section(layer_list, 'os'))
    components = {}
    for name, (spec, src, shadows) in layers.merge_named(layer_list, 'components').items():
        try:
            comp = Component(name, spec or {})
        except ConfigError as e:
            raise ConfigError(f'{src}: {e}')
        comp.source = src
        comp.shadows = shadows
        components[name] = comp

    mechs = layers.repo_section(layer_list, 'mechanisms')
    mechanisms = {name: _as_list((spec or {}).get('requires')) for name, spec in mechs.items()}
    if validate:
        from . import routecheck
        routecheck.check_all(components, cascade)
    return cascade, components, mechanisms


class Resolver:
    '''The app-facing resolver: load routes.hu once, then resolve a profile's component
    names to `{key: ResolvedComponent}` for this machine's context (OS block + version +
    cpu). `resolve_with_roots` also returns the directly-bound unit keys the app applies
    an op to (dependency installs are folded in by planning.expand_plan).'''

    def __init__(self, routes_path, block, version=None, cpu=None, pins=None,
                 overrides_path=None):
        self.cascade, self.components, self.mechanisms = load(routes_path, overrides_path)
        self.block = block
        self.version = version
        self.cpu = cpu
        self.pins = pins or {}

    @property
    def cascade_names(self):
        '''The OS lineage leaf-first (e.g. rhel -> redhat -> linux), for display/tests.'''
        return self.cascade.lineage(self.block)

    def _resolve(self, names):
        from .resolve import resolve_roots
        return resolve_roots(list(names), self.cascade, self.components, self.mechanisms,
                             self.block, self.version, self.cpu, self.pins)

    def resolve_names(self, names):
        from .adapt import to_resolved_components
        return to_resolved_components(self._resolve(names)[0])

    def resolve_with_roots(self, names):
        from .adapt import to_resolved_components
        units, roots = self._resolve(names)
        return to_resolved_components(units), roots
