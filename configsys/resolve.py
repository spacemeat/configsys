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
        # install-execution fields (the family reads these off the ResolvedComponent the
        # builder makes). Populated from the selected binding's details / the dotfiles spec,
        # minus resolver-only keys; `name` is normalized to the resolved package.
        self.details = {}

    @property
    def key(self):
        return f'{self.mechanism}\\{self.component}'

    def as_tuple(self):
        return (self.mechanism, self.component, self.package)

    def __repr__(self):
        return f'Unit({self.key} -> {self.package!r})'


def select_binding(component, cascade, context, pins=None):
    bindings = component.bindings
    pin = (pins or {}).get(component.name)
    if pin is not None:                     # binding-pin: force this method, still context-valid
        bindings = [b for b in bindings if b.via == pin]
        if not bindings:
            raise ResolveError(f'{component.name}: pinned to via:{pin!r}, which is not a binding')
    matching = [b for b in bindings if b.pred.eval(context)]
    if not matching:
        extra = f' (pinned to via:{pin!r})' if pin is not None else ''
        raise ResolveError(f'no binding for {component.name} in this context{extra}')
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


# keys that steer resolution, not installation — never handed to a family.
_RESOLVER_KEYS = ('requires', 'parts', 'app')


def _install_fields(details, package):
    '''The install-execution fields a family reads, from a binding's details (or an inline
    dotfiles spec). Resolver-only keys are dropped; `name` is normalized to the concrete
    resolved package (so flatpak `app:` -> name, native name-maps -> the picked package).'''
    fields = {k: v for k, v in details.items() if k not in _RESOLVER_KEYS}
    fields.pop('name', None)
    if package is not None:
        fields['name'] = package
    return fields


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

def resolve(names, cascade, components, mechanisms, block, version=None, cpu=None, pins=None):
    '''Resolve a profile (component names) to the full unit closure for a context.

    Phase 1 seeds every explicit want and registers what it provides, BEFORE any
    requirement is resolved — so an explicitly-requested provider always wins over an
    implicitly-pulled one. Phase 2 drains requirements to a fixpoint, reusing whatever
    the environment or an already-chosen unit provides. No backtracking: unsatisfiable
    or ambiguous is an error. `pins` (per-machine) force a component's method
    (binding-pin) or a capability's provider (provider-pin), top of precedence.
    Returns {unit_key: Unit}. Resolving a name yields a SET of keys — one for a normal
    component, several for a `via: parts` aggregator (which has no unit of its own).
    '''
    return resolve_roots(names, cascade, components, mechanisms, block, version, cpu, pins)[0]


def resolve_roots(names, cascade, components, mechanisms, block, version=None, cpu=None, pins=None):
    '''Like resolve(), but also return the set of unit keys bound *directly* by the named
    components (a named parts-component contributes its parts' keys; family/mechanism deps
    are not roots). The app applies the requested op to these, and expand_plan folds in deps.'''
    st = _State(cascade, components, mechanisms, cascade.context(block, version, cpu), pins or {})
    roots = set()
    for name in names:
        roots |= st.add_component(name, root=name)  # phase 1: wants + their provides
    st.drain()                                      # phase 2: close requirements
    st.propagate_requested()
    return st.units, roots


def _bindable(component, cascade, ctx, pins):
    try:
        select_binding(component, cascade, ctx, pins)
        return True
    except ResolveError:
        return False


class _State:
    def __init__(self, cascade, components, mechanisms, ctx, pins):
        self.cascade = cascade
        self.components = components
        self.mechanisms = mechanisms
        self.ctx = ctx
        self.pins = pins
        self.block = ctx.lineage[0]
        self.units = {}
        # capability -> frozenset of unit keys satisfying it (empty = the environment
        # provides it, no unit needed).
        self.inventory = {cap: frozenset() for cap in cascade.provides(self.block)}
        self.providers = self._provider_index()
        self.queue = []                            # (requiring_key, requiring_name, cap, root)

    def _provider_index(self):
        idx = {}
        for name, comp in self.components.items():
            for cap in set(comp.provides) | {name}:     # a component always provides its own name
                idx.setdefault(cap, []).append(name)
        return idx

    def add_component(self, name, root):
        '''Resolve a component name -> the frozenset of unit keys it contributes.'''
        if name not in self.components:
            raise ResolveError(f'unknown component: {name}')
        comp = self.components[name]
        binding = select_binding(comp, self.cascade, self.ctx, self.pins)

        # a `via: parts` binding is a pure aggregator: no unit of its own, just the
        # union of its (recursively resolved) parts, each attributed to this root.
        if binding.via == 'parts':
            keys = set()
            for part in _as_list(binding.details.get('parts')):
                keys |= self.add_component(part, root)
            return frozenset(keys)

        mech = _mechanism(binding, self.cascade, self.block)
        key = f'{mech}\\{name}'
        if key in self.units:
            self.units[key].requested_as.add(root)
            return frozenset({key})
        unit = Unit(mech, name, _package(binding, mech, comp))
        unit.requested_as = {root}
        unit.details = _install_fields(binding.details, unit.package)
        self.units[key] = unit
        for cap in set(comp.provides) | {name}:
            self.inventory.setdefault(cap, frozenset({key}))
        # requires: method-independent (component) + mechanism-level + binding-specific.
        # A component's config is just another required component (a `via: dotfiles` one),
        # so it flows through here too — no special-cased dotfiles field.
        reqs = (list(comp.requires) + list(self.mechanisms.get(binding.via, []))
                + _as_list(binding.details.get('requires')))
        for cap in reqs:
            self.queue.append((key, name, cap, root))
        return frozenset({key})

    def drain(self):
        while self.queue:
            requiring_key, requiring_name, cap, root = self.queue.pop(0)
            self.units[requiring_key].deps |= self._satisfy(cap, root, requiring_name)

    def _satisfy(self, cap, root, requiring):
        if cap in self.inventory:
            return self.inventory[cap]                  # reuse (keys, or empty for env)
        candidates = [p for p in self.providers.get(cap, []) if p != requiring]  # bootstrap guard
        viable = [p for p in candidates if _bindable(self.components[p], self.cascade, self.ctx, self.pins)]
        if not viable:
            raise ResolveError(f'nothing provides "{cap}" here (required by {requiring})')
        pin = self.pins.get(cap)
        if pin is not None:                             # provider-pin
            if pin not in viable:
                raise ResolveError(f'"{cap}" pinned to {pin!r}, which cannot provide it here')
            chosen = pin
        elif len(viable) == 1:
            chosen = viable[0]
        else:
            raise ResolveError(f'ambiguous providers for "{cap}": {sorted(viable)} '
                               f'(required by {requiring}) — needs a provider-pin')
        keys = self.add_component(chosen, root)
        self.inventory[cap] = keys
        return keys

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
