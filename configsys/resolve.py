'''resolve.py — resolution: pick each component's binding for a context and report the
concrete unit closure (worklist to a fixpoint over requires/provides/parts).
'''

from . import predicate
from .errors import ConfigsysError


class ResolveError(ConfigsysError):
    '''A component could not be routed here (unknown name, no binding, unsatisfiable
    requirement, ambiguity). A ConfigsysError so the app surfaces it as a clean message.'''


# sentinel: no `component-names` entry for this (driver, component) — distinct from an entry
# whose value is `{}`/null (a DROP: the driver has no package for the component here).
_NO_OVERRIDE = object()


def _name_override(overrides, driver, component):
    '''(override, drop) for a (driver, component) `component-names` entry. override is the
    replacement package string (or _NO_OVERRIDE if none); drop is True when the entry is present
    but not a non-empty string (`{}`/null/"") -> the driver packages nothing for it here.'''
    val = (overrides or {}).get(driver, {}).get(component, _NO_OVERRIDE)
    if val is _NO_OVERRIDE:
        return _NO_OVERRIDE, False
    if isinstance(val, str) and val.strip():
        return val, False
    return _NO_OVERRIDE, True


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


class Unit:
    '''A resolved leaf: which driver installs it, the component name, and the concrete
    package identifier. Shaped to line up with the old resolver's (driver, comp, name).
    `deps` are the unit keys it depends on; `requested_as` are the roots that pulled it.'''

    def __init__(self, driver, component, package):
        self.driver = driver
        self.component = component
        self.package = package
        self.deps = set()
        self.requested_as = set()
        self.source = None      # the .hu file that DEFINED the component (layer-relative content roots)
        # install-execution fields (the driver reads these off the ResolvedComponent the
        # builder makes). Populated from the selected binding's details / the dotfiles spec,
        # minus resolver-only keys; `name` is normalized to the resolved package.
        self.details = {}

    @property
    def key(self):
        return f'{self.driver}\\{self.component}'

    def as_tuple(self):
        return (self.driver, self.component, self.package)

    def __repr__(self):
        return f'Unit({self.key} -> {self.package!r})'


# Default order for choosing among genuinely-alternative install methods (same context, no
# most-specific winner). A machine may replace this globally (config `driver-preference:`) or an
# OS block may override it (`driver-preference:` in the os: layer). Native-first is conventional;
# drivers absent from the list are least-preferred and tie among themselves (a tie is an error,
# not a silent guess). snap/source are listed ahead of their drivers existing — harmless.
DEFAULT_DRIVER_PREFERENCE = ['native', 'flatpak', 'snap', 'appImage', 'tarball', 'source', 'script']


def _matching(component, context, pins):
    '''(bindings valid in this context, the binding-pin or None). A binding-pin filters to that
    via first (still subject to `when:`); `when:` alone decides validity.'''
    bindings = component.bindings
    pin = (pins or {}).get(component.name)
    if pin is not None:                     # binding-pin: force this method, still context-valid
        bindings = [b for b in bindings if b.via == pin]
        if not bindings:
            raise ResolveError(f'{component.name}: pinned to via:{pin!r}, which is not a binding')
    return [b for b in bindings if b.pred.eval(context)], pin


def candidate_bindings(component, cascade, context, pins=None):
    '''Every `when:`-valid binding for this context — the honest candidate set (the install
    methods available here), for the picker / `where` introspection. `when:` is validity only:
    this never narrows the set to force one winner. Unordered.'''
    return _matching(component, context, pins)[0]


def _prefer_rank(binding):
    '''The binding's explicit `prefer:` rank (higher wins), default 0.'''
    try:
        return int(binding.details.get('prefer'))
    except (TypeError, ValueError):
        return 0


def _effective_preference(cascade, context, preference):
    '''The driver-preference order for this context: the nearest OS block's `driver-preference:`
    (walking the lineage) wins, else the passed-in global (config) list, else the built-in.'''
    for name in context.lineage:
        pref = (cascade.blocks.get(name) or {}).get('driver-preference')
        if pref:
            return _as_list(pref)
    return list(preference) if preference else list(DEFAULT_DRIVER_PREFERENCE)


def _most_specific_binding(matching, cascade):
    '''The unique binding whose `when:` is ⊆ every other matching binding's, or None when the
    candidates are incomparable OR several share the most-specific `when:` (genuine alternatives —
    the preference channel decides those). Operates over bindings, not deduped predicates, so two
    same-`when:` different-`via:` bindings are correctly seen as a tie, not silently collapsed.'''
    mins = [b for b in matching
            if all(predicate.subset(b.pred, o.pred, cascade) for o in matching)]
    return mins[0] if len(mins) == 1 else None


def _by_preference(matching, component, cascade, context, preference):
    '''Pick among incomparable/equally-specific candidates via the preference channel — separate
    from `when:`. Order: explicit `prefer:` (higher wins), then driver-preference index. A true
    tie is a ResolveError that points at the preference channel, NEVER at narrowing `when:`.'''
    order = _effective_preference(cascade, context, preference)

    def key(b):
        return (-_prefer_rank(b), order.index(b.via) if b.via in order else len(order))

    ranked = sorted(matching, key=key)
    best = ranked[0]
    if key(ranked[1]) == key(best):
        tied = sorted({b.via for b in ranked if key(b) == key(best)})
        raise ResolveError(
            f'{component.name}: install methods {tied} are equally valid AND equally preferred '
            f'here — set a `driver-preference` order or a per-binding `prefer:` to choose one '
            f'(do not narrow `when:`: every one of these methods genuinely works here)')
    rule = 'prefer:' if _prefer_rank(best) != _prefer_rank(ranked[1]) else 'driver-preference'
    return best, rule


def _select(component, cascade, context, pins=None, preference=None):
    '''-> (winning Binding, [all candidates], reason). Candidates = `when:`-valid bindings
    (validity only). The default among them: the single most-specific `when:`, else the
    preference channel. Raises ResolveError if nothing is valid or the choice is undecidable.'''
    matching, pin = _matching(component, context, pins)
    if not matching:
        extra = f' (pinned to via:{pin!r})' if pin is not None else ''
        raise ResolveError(f'no binding for {component.name} in this context{extra}')
    if len(matching) == 1:
        return matching[0], matching, 'only method here'
    ms = _most_specific_binding(matching, cascade)
    if ms is not None:
        return ms, matching, 'most-specific when:'
    winner, rule = _by_preference(matching, component, cascade, context, preference)
    return winner, matching, rule


def select_binding(component, cascade, context, pins=None, preference=None):
    '''The one binding that resolves here (the default method). See _select.'''
    return _select(component, cascade, context, pins, preference)[0]


def _driver(binding, cascade, block):
    if binding.via == 'native':
        drv = cascade.native(block)
        if drv is None:
            raise ResolveError(f'no native package manager on {block}')
        return drv
    return binding.via


def _package(binding, driver, component):
    if binding.via == 'native':
        name = binding.details.get('name')
        if isinstance(name, dict):
            return name.get(driver) or name.get('default') or component.name
        return name or component.name
    if binding.via == 'flatpak':
        return binding.details.get('app')
    if binding.via == 'dotfiles':
        return None                     # a dotfile has no package
    # appImage / deb / tarball / crate / font: the display/dist name
    return binding.details.get('name') or component.name


# keys that steer resolution, not installation — never handed to a driver.
_RESOLVER_KEYS = ('requires', 'suggests', 'parts', 'app', 'prefer')


def _install_fields(details, package):
    '''The install-execution fields a driver reads, from a binding's details (or an inline
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


def resolve_one(name, cascade, components, block, version=None, cpu=None, overrides=None,
                preference=None):
    if name not in components:
        raise ResolveError(f'unknown component: {name}')
    comp = components[name]
    ctx = cascade.context(block, version, cpu)
    binding = select_binding(comp, cascade, ctx, None, preference)
    drv = _driver(binding, cascade, block)
    override, drop = _name_override(overrides, drv, name)
    if drop:
        raise ResolveError(f'{name}: no {drv} package here (dropped by component-names)')
    package = override if override is not _NO_OVERRIDE else _package(binding, drv, comp)
    return Unit(drv, name, package)


# -- full resolution: the worklist to a fixpoint ---------------------------

def resolve(names, cascade, components, drivers, block, version=None, cpu=None, pins=None,
            overrides=None, preference=None):
    '''Resolve a profile (component names) to the full unit closure for a context.

    Phase 1 seeds every explicit want and registers what it provides, BEFORE any
    requirement is resolved — so an explicitly-requested provider always wins over an
    implicitly-pulled one. Phase 2 drains requirements to a fixpoint, reusing whatever
    the environment or an already-chosen unit provides. No backtracking: unsatisfiable
    or ambiguous is an error. `pins` (per-machine) force a component's method
    (binding-pin) or a capability's provider (provider-pin), top of precedence.
    `overrides` (the merged `component-names` section) patches a component's package name
    per driver, or drops it where the driver has no package (a plugin OS supplying its own
    names for existing components without redefining them).
    Returns {unit_key: Unit}. Resolving a name yields a SET of keys — one for a normal
    component, several for a `via: parts` aggregator (which has no unit of its own).
    '''
    return resolve_roots(names, cascade, components, drivers, block, version, cpu, pins,
                         overrides, preference)[0]


def resolve_roots(names, cascade, components, drivers, block, version=None, cpu=None, pins=None,
                  overrides=None, preference=None):
    '''Like resolve(), but also return the set of unit keys bound *directly* by the named
    components (a named parts-component contributes its parts' keys; driver/driver deps
    are not roots). The app applies the requested op to these, and expand_plan folds in deps.'''
    st = _State(cascade, components, drivers, cascade.context(block, version, cpu), pins or {},
                overrides or {}, preference)
    roots = set()
    for name in names:
        roots |= st.add_component(name, root=name)  # phase 1: wants + their provides
    st.drain()                                      # phase 2: close requirements
    st.propagate_requested()
    return st.units, roots


def resolve_resilient(names, cascade, components, drivers, block, version=None, cpu=None,
                      pins=None, overrides=None, preference=None):
    '''Resilient resolution for the inspect/TUI pipeline: a requested name that can't resolve
    (unknown, no binding here, or an unsatisfiable requirement) is collected into `errors`
    instead of aborting the whole set — everything resolvable still resolves. Returns
    (units, errors) with errors = {requested_name: message}. So one broken component in the
    active set (e.g. from an auto-activated project profile) can't brick the tool.'''
    st = _State(cascade, components, drivers, cascade.context(block, version, cpu), pins or {},
                overrides or {}, preference)
    errors = {}
    for name in names:
        try:
            st.add_component(name, root=name)
        except ResolveError as e:
            errors[name] = str(e)
    st.drain(errors=errors)
    st.propagate_requested()
    return st.units, errors


def _bindable(component, cascade, ctx, pins, preference=None):
    try:
        select_binding(component, cascade, ctx, pins, preference)
        return True
    except ResolveError:
        return False


class _State:
    def __init__(self, cascade, components, drivers, ctx, pins, overrides=None, preference=None):
        self.cascade = cascade
        self.components = components
        self.drivers = drivers
        self.ctx = ctx
        self.pins = pins
        self.preference = preference       # driver-preference order (config global); None = built-in
        self.overrides = overrides or {}   # {driver: {component: pkg-or-drop}} (component-names)
        self.block = ctx.lineage[0]
        self.units = {}
        # capability -> frozenset of unit keys satisfying it (empty = the environment
        # provides it, no unit needed).
        self.inventory = {cap: frozenset() for cap in cascade.provides(self.block)}
        self.providers = self._provider_index()
        # opt-in providers are never AUTO-pulled to close a requirement — only used when the
        # component is explicitly wanted (then it's in inventory before we look for candidates)
        # or named by a provider-pin. Keeps a best-effort shim (gcompat) from installing itself.
        self.optin = {n for n, c in components.items() if getattr(c, 'opt_in', False)}
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
        # a component with NO bindings is "removed" (a user override `{}`): it contributes
        # nothing and is a no-op when named directly. This differs from a component that HAS
        # bindings but none match the context (select_binding below errors "no binding here").
        if not comp.bindings:
            return frozenset()
        binding = select_binding(comp, self.cascade, self.ctx, self.pins, self.preference)

        # a `via: parts` binding is a pure aggregator: no unit of its own, just the
        # union of its (recursively resolved) parts, each attributed to this root.
        if binding.via == 'parts':
            keys = set()
            for part in _as_list(binding.details.get('parts')):
                keys |= self.add_component(part, root)
            return frozenset(keys)

        drv = _driver(binding, self.cascade, self.block)
        override, drop = _name_override(self.overrides, drv, name)
        if drop:
            # this driver packages nothing for the component here -> drop it (a silent no-op,
            # exactly like a `{}`-removed component): not offered, never an error row.
            return frozenset()
        key = f'{drv}\\{name}'
        if key in self.units:
            self.units[key].requested_as.add(root)
            return frozenset({key})
        package = override if override is not _NO_OVERRIDE else _package(binding, drv, comp)
        unit = Unit(drv, name, package)
        unit.requested_as = {root}
        unit.details = _install_fields(binding.details, unit.package)
        unit.source = comp.source        # the layer/file this component came from
        self.units[key] = unit
        for cap in set(comp.provides) | {name}:
            self.inventory.setdefault(cap, frozenset({key}))
        # requires (HARD): method-independent (component) + driver-level + binding-specific.
        # A component's config is just another required component (a `via: dotfiles` one),
        # so it flows through here too — no special-cased dotfiles field.
        reqs = (list(comp.requires) + list(self.drivers.get(binding.via, []))
                + _as_list(binding.details.get('requires')))
        for cap in reqs:
            self.queue.append((key, name, cap, root, False))
        # suggests (SOFT): pulled in if resolvable in the loaded layers, skipped silently if
        # not — the edge is optional (a package's dotfiles that may live only in a user layer).
        # A suggested component's OWN requires stay hard once it is pulled.
        for cap in list(comp.suggests) + _as_list(binding.details.get('suggests')):
            self.queue.append((key, name, cap, root, True))
        return frozenset({key})

    def drain(self, errors=None):
        '''Close requirements to a fixpoint. Strict by default (a missing/ambiguous HARD
        provider raises). If `errors` is given, catch such failures into it (keyed by the
        requesting root) and keep going. A SOFT edge (`suggests:`) that can't be satisfied here
        is skipped silently — never an error, in either mode.'''
        while self.queue:
            requiring_key, requiring_name, cap, root, optional = self.queue.pop(0)
            try:
                self.units[requiring_key].deps |= self._satisfy(cap, root, requiring_name)
            except ResolveError as e:
                if optional:
                    continue                     # a `suggests:` unmet here is simply not pulled
                if errors is None:
                    raise
                errors.setdefault(root, str(e))

    def _satisfy(self, cap, root, requiring):
        if cap in self.inventory:
            return self.inventory[cap]                  # reuse (keys, or empty for env)
        candidates = [p for p in self.providers.get(cap, []) if p != requiring]  # bootstrap guard
        viable = [p for p in candidates
                  if _bindable(self.components[p], self.cascade, self.ctx, self.pins, self.preference)]
        if not viable:
            raise ResolveError(f'nothing provides "{cap}" here (required by {requiring})')
        pin = self.pins.get(cap)
        if pin is not None:                             # provider-pin (may name an opt-in one)
            if pin not in viable:
                raise ResolveError(f'"{cap}" pinned to {pin!r}, which cannot provide it here')
            chosen = pin
        else:
            auto = [p for p in viable if p not in self.optin]   # opt-in ones need a pin/explicit want
            if not auto:
                hint = f' — enable one with a provider-pin, e.g. pins: {{ {cap}: {viable[0]} }}'
                raise ResolveError(f'nothing auto-provides "{cap}" here (required by {requiring}){hint}')
            if len(auto) == 1:
                chosen = auto[0]
            else:
                raise ResolveError(f'ambiguous providers for "{cap}": {sorted(auto)} '
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
