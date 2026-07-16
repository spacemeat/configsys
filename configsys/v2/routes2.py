'''routes2.py — load the v2 routes file into an OS cascade + components.

Thin, deliberately: it turns humon nodes into small dataclasses the resolver walks.
Only the constructs the ported components need are handled; it grows with the port.
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
    def __init__(self, name, spec):
        self.name = name
        self.provides = _as_list(spec.get('provides'))
        self.requires = _as_list(spec.get('requires'))
        self.parts = _as_list(spec.get('parts'))
        self.dotfiles = spec.get('dotfiles')
        self.bindings = [Binding(b) for b in (spec.get('install') or [])]


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _truthy(v):
    return str(v).lower() in ('true', 'yes', '1')


class OsCascade:
    '''The OS layer: `using` inheritance, the `native` mechanism, and scale-roots.'''

    def __init__(self, os_dict):
        self.blocks = os_dict
        self.scale_roots = {n for n, b in os_dict.items()
                            if isinstance(b, dict) and _truthy(b.get('scale-root'))}

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


def load(path):
    '''-> (OsCascade, {component_name: Component}).'''
    trove = humon.from_file(path)          # keep the trove alive via the returned objects? no —
    root = trove.root                      # _py fully materializes, so the trove can be dropped.
    os_dict = _py(root['os']) or {}
    comps = _py(root['components']) or {}
    cascade = OsCascade(os_dict)
    components = {name: Component(name, spec) for name, spec in comps.items()}
    return cascade, components
