'''routes.py — load routes.hu into an OS cascade + components, and the app-facing Resolver.

Turns humon nodes into small dataclasses the resolver walks (OsCascade / Component /
Binding), validates the file (ambiguity check), and exposes `Resolver`: the object the app
holds to turn a profile's component names into the `{key: ResolvedComponent}` closure for
this machine's context. Resolution itself lives in resolve.py; the RC marshalling in adapt.py.
'''

import humon

from . import predicate


def _py(node):
    '''humon node -> python (dict / list / str), or None for a missing node.'''
    if node is None:
        return None
    kind = node.kind
    if kind == humon.NodeKind.DICT:
        out = {}
        for i in range(node.num_children):
            ch = node[i]
            if ch.key:
                out[ch.key] = _py(ch)
        return out
    if kind == humon.NodeKind.LIST:
        return [_py(node[i]) for i in range(node.num_children)]
    return node.value


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
        unknown = set(spec) - self._KEYS
        if unknown:
            raise ValueError(
                f'component {name!r}: unknown key(s) {sorted(unknown)} '
                f'(config is a required `<name>-dotfiles` component now, not a `dotfiles:` field)')
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


def load(path, validate=True):
    '''-> (OsCascade, {component_name: Component}, {mechanism: [required caps]}).

    The trove must stay alive while _py walks its nodes (they point into it); once _py
    has materialized everything to plain python, the returned objects don't need it.
    With validate=True, an ambiguous routes file is rejected up front (AmbiguityError).
    '''
    trove = humon.from_file(path)
    root = trove.root
    os_dict = _py(root['os']) or {}
    comps = _py(root['components']) or {}
    mechs = _py(root['mechanisms']) or {}
    cascade = OsCascade(os_dict)
    components = {name: Component(name, spec) for name, spec in comps.items()}
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

    def __init__(self, routes_path, block, version=None, cpu=None, pins=None):
        self.cascade, self.components, self.mechanisms = load(routes_path)
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
