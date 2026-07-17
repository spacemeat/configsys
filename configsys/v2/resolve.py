'''resolve.py — minimal v2 resolution: pick a component's binding for a context and
report the concrete unit. Single-component for now (no dependency graph yet — that's the
worklist/fixpoint slice); enough to prove binding selection matches the old resolver.
'''

from . import predicate


class ResolveError(Exception):
    pass


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


class Unit:
    '''A resolved leaf: which mechanism installs it, the component name, and the concrete
    package identifier. Shaped to line up with the old resolver's (family, comp, name).
    `deps` are the unit keys it depends on; `requested_as` are the roots that pulled it.'''

    def __init__(self, mechanism, component, package):
        self.mechanism = mechanism
        self.component = component
        self.package = package
        self.deps = set()
        self.requested_as = set()

    @property
    def key(self):
        return f'{self.mechanism}\\{self.component}'

    def as_tuple(self):
        return (self.mechanism, self.component, self.package)

    def __repr__(self):
        return f'Unit({self.key} -> {self.package!r})'


def select_binding(component, cascade, context):
    matching = [b for b in component.bindings if b.pred.eval(context)]
    if not matching:
        raise ResolveError(f'no binding for {component.name} in this context')
    if len(matching) == 1:
        return matching[0]
    by_pred = {b.pred: b for b in matching}
    winner = predicate.most_specific(list(by_pred), cascade)
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
    if binding.via == 'dotfiles':
        return None                     # a dotfile has no package
    # appImage / deb / tarball / crate / font: the display/dist name
    return binding.details.get('name') or component.name


def resolve_asset(binding, cpu):
    '''The concrete artifact for this cpu. The arch-relevant `asset` may sit at the
    binding top level (an explicit cpu-keyed map, e.g. the fastfetch .deb) or inside a
    github `version:` discovery spec (an $ARCH glob, e.g. the neovim appImage). A dict
    picks by cpu; a string has $ARCH substituted.'''
    asset = binding.details.get('asset')
    if asset is None:
        ver = binding.details.get('version')
        asset = ver.get('asset') if isinstance(ver, dict) else None
    if isinstance(asset, dict):
        return asset.get(cpu)
    if isinstance(asset, str) and cpu:
        return asset.replace('$ARCH', cpu)
    return asset


def resolve_one(name, cascade, components, block, version=None, cpu=None):
    if name not in components:
        raise ResolveError(f'unknown component: {name}')
    comp = components[name]
    ctx = cascade.context(block, version, cpu)
    binding = select_binding(comp, cascade, ctx)
    mech = _mechanism(binding, cascade, block)
    return Unit(mech, name, _package(binding, mech, comp))


# -- full resolution: the worklist to a fixpoint ---------------------------

def resolve(names, cascade, components, mechanisms, block, version=None, cpu=None):
    '''Resolve a profile (component names) to the full unit closure for a context.

    Phase 1 seeds every explicit want and registers what it provides, BEFORE any
    requirement is resolved — so an explicitly-requested provider always wins over an
    implicitly-pulled one. Phase 2 drains requirements to a fixpoint, reusing whatever
    the environment or an already-chosen unit provides. No backtracking: unsatisfiable
    or ambiguous is an error. Returns {unit_key: Unit}.
    '''
    st = _State(cascade, components, mechanisms, cascade.context(block, version, cpu))
    for name in names:
        st.add_component(name, root=name)          # phase 1: wants + their provides
    st.drain()                                     # phase 2: close requirements
    st.propagate_requested()
    return st.units


def _bindable(component, cascade, ctx):
    return any(b.pred.eval(ctx) for b in component.bindings)


class _State:
    def __init__(self, cascade, components, mechanisms, ctx):
        self.cascade = cascade
        self.components = components
        self.mechanisms = mechanisms
        self.ctx = ctx
        self.block = ctx.lineage[0]
        self.units = {}
        self.inventory = {cap: None for cap in cascade.provides(self.block)}   # cap -> unit key (None = env)
        self.providers = self._provider_index()
        self.queue = []                            # (requiring_key, requiring_name, cap, root)

    def _provider_index(self):
        idx = {}
        for name, comp in self.components.items():
            for cap in set(comp.provides) | {name}:     # a component always provides its own name
                idx.setdefault(cap, []).append(name)
        return idx

    def add_component(self, name, root):
        if name not in self.components:
            raise ResolveError(f'unknown component: {name}')
        comp = self.components[name]
        binding = select_binding(comp, self.cascade, self.ctx)
        mech = _mechanism(binding, self.cascade, self.block)
        key = f'{mech}\\{name}'
        if key in self.units:
            self.units[key].requested_as.add(root)
            return key
        unit = Unit(mech, name, _package(binding, mech, comp))
        unit.requested_as = {root}
        self.units[key] = unit
        for cap in set(comp.provides) | {name}:
            self.inventory.setdefault(cap, key)
        # requires: method-independent (component) + mechanism-level + binding-specific
        reqs = (list(comp.requires) + list(self.mechanisms.get(binding.via, []))
                + _as_list(binding.details.get('requires')))
        for cap in reqs:
            self.queue.append((key, name, cap, root))
        # method-independent config: a `dotfiles:` field emits a dotfiles\<comp> unit
        # (keyed by the component) as a dependency, with its own requires (e.g. bashDotD).
        if comp.dotfiles is not None:
            self._add_dotfile(name, comp.dotfiles, root)
            unit.deps.add(f'dotfiles\\{name}')
        return key

    def _add_dotfile(self, name, spec, root):
        key = f'dotfiles\\{name}'
        if key in self.units:
            self.units[key].requested_as.add(root)
            return
        unit = Unit('dotfiles', name, None)
        unit.requested_as = {root}
        self.units[key] = unit
        for cap in _as_list(spec.get('requires')):
            self.queue.append((key, name, cap, root))

    def drain(self):
        while self.queue:
            requiring_key, requiring_name, cap, root = self.queue.pop(0)
            dep = self._satisfy(cap, root, requiring_name)
            if dep is not None:
                self.units[requiring_key].deps.add(dep)

    def _satisfy(self, cap, root, requiring):
        if cap in self.inventory:
            return self.inventory[cap]                  # reuse (a unit key, or None for env)
        candidates = [p for p in self.providers.get(cap, []) if p != requiring]  # bootstrap guard
        viable = [p for p in candidates if _bindable(self.components[p], self.cascade, self.ctx)]
        if not viable:
            raise ResolveError(f'nothing provides "{cap}" here (required by {requiring})')
        if len(viable) > 1:
            raise ResolveError(f'ambiguous providers for "{cap}": {sorted(viable)} '
                               f'(required by {requiring}) — needs a pin')
        key = self.add_component(viable[0], root)
        self.inventory[cap] = key
        return key

    def propagate_requested(self):
        changed = True
        while changed:
            changed = False
            for unit in self.units.values():
                for dk in unit.deps:
                    dep = self.units.get(dk)
                    if dep is not None and not unit.requested_as <= dep.requested_as:
                        dep.requested_as |= unit.requested_as
                        changed = True
