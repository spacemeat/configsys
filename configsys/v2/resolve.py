'''resolve.py — minimal v2 resolution: pick a component's binding for a context and
report the concrete unit. Single-component for now (no dependency graph yet — that's the
worklist/fixpoint slice); enough to prove binding selection matches the old resolver.
'''

from . import predicate


class ResolveError(Exception):
    pass


class Unit:
    '''A resolved leaf: which mechanism installs it, the component name, and the concrete
    package identifier. Shaped to line up with the old resolver's (family, comp, name).'''

    def __init__(self, mechanism, component, package):
        self.mechanism = mechanism
        self.component = component
        self.package = package

    def as_tuple(self):
        return (self.mechanism, self.component, self.package)

    def __repr__(self):
        return f'Unit({self.mechanism}\\{self.component} -> {self.package!r})'


def select_binding(component, cascade, context):
    matching = [b for b in component.bindings if b.pred.eval(context)]
    if not matching:
        raise ResolveError(f'no binding for {component.name} in this context')
    if len(matching) == 1:
        return matching[0]
    by_pred = {b.pred: b for b in matching}
    winner = predicate.most_specific(list(by_pred), cascade.is_descendant)
    return by_pred[winner]


def _mechanism(binding, cascade, block):
    if binding.via == 'native':
        mech = cascade.native(block)
        if mech is None:
            raise ResolveError(f'no native package manager on {block}')
        return mech
    return binding.via


def _package(binding, mechanism, component):
    if binding.via == 'native':
        name = binding.details.get('name')
        if isinstance(name, dict):
            return name.get(mechanism) or name.get('default') or component.name
        return name or component.name
    if binding.via == 'flatpak':
        return binding.details.get('app')
    # other mechanisms (appImage, deb, crate, ...) fill in as they're ported
    return binding.details.get('name') or component.name


def resolve_one(name, cascade, components, block, version=None, cpu=None):
    if name not in components:
        raise ResolveError(f'unknown component: {name}')
    comp = components[name]
    ctx = cascade.context(block, version, cpu)
    binding = select_binding(comp, cascade, ctx)
    mech = _mechanism(binding, cascade, block)
    return Unit(mech, name, _package(binding, mech, comp))
