'''resolve.py — resolution: pick each component's binding for a context and report the
concrete unit closure (worklist to a fixpoint over requires/provides/parts).
'''

import os
from collections import deque

from . import predicate, trustgate
from .errors import ConfigsysError
from .layers import as_list


class ResolveError(ConfigsysError):
    '''A component could not be routed here (unknown name, no binding, unsatisfiable
    requirement, ambiguity). A ConfigsysError so the app surfaces it as a clean message. `kind`
    (one of KINDS) says which, set where it is raised — so a consumer switches on it instead of
    reading the message text (routing-28).'''
    default_kind = None

    def __init__(self, message='', kind=None):
        super().__init__(message)
        self.kind = kind or self.default_kind


class AmbiguityError(ResolveError):
    '''Two equally-ranked providers of a capability — a decision the user makes (a provider-pin or a
    `standing:` rank). Unlike an unmet requirement it never closes a derived driver gate (B15).'''
    default_kind = 'ambiguous-providers'


class PartsCycleError(ResolveError):
    '''A `parts:` bundle that contains itself — structural, never skipped like an unroutable part.'''
    default_kind = 'parts-cycle'


# What a ResolveError is about: an unknown name; no candidate method here (none valid, or only ones a
# driver gate / disabled driver / untrusted layer removed: 'gated'); a hard requirement nothing meets;
# two equally-ranked providers; two equally-preferred methods; a pin that can't be honored; a parts loop.
KINDS = ('unknown', 'no-candidate', 'gated', 'unmet-require', 'ambiguous-providers', 'method-tie',
         'pin-unrealizable', 'parts-cycle')
# the kinds that are the CONFIG's to fix (a pin, a preference, a rank) — `check` reports these as errors
CONFIG_ERROR_KINDS = frozenset({'pin-unrealizable', 'ambiguous-providers', 'method-tie'})

# the vias that name no Driver of their own: `native` (the OS's manager) and `parts` (an aggregator)
SPECIAL_VIAS = frozenset({'native', 'parts'})


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


def pin_via_names():
    '''The set of `pins:` values that name an install METHOD (a via/driver) rather than a provider
    component — `native`, `parts`, and every registered driver. A flat-`pins:` value in this set is
    a BINDING-pin (component -> via); anything else that is a known component is a PROVIDER-pin. Used
    identically by resolve, actions.validate_pin and routecheck so all three classify a pin the same
    way — critical when a name is BOTH a via and a component (pyenv, flatpak, clang, cabal, …).'''
    from .drivers import supported_names
    return SPECIAL_VIAS | supported_names()


def cap_names(raw):
    '''Capability NAMES from a requires/provides/suggests value that may mix bare names with
    versioned `{ cap: constraint }` maps. Names only — the resolver closes on these UNCHANGED
    (a versioned entry contributes exactly its capability name); version constraints are read
    separately via cap_constraints, so adding a floor never alters which units resolve.'''
    names = []
    for item in as_list(raw):
        if isinstance(item, dict):
            names.extend(item.keys())
        else:
            names.append(item)
    return names


def cap_constraints(raw):
    '''{ cap: constraint-string } for the versioned entries of a requires/provides/suggests value;
    {} when none carry a version. The constraint reuses the when:-DSL comparison vocabulary
    (`>=1.96`, `>1.0`, `=2.0`, and `,`-AND ranges).'''
    cons = {}
    for item in as_list(raw):
        if isinstance(item, dict):
            for k, v in item.items():
                cons[k] = str(v)
    return cons


class Unit:
    '''A resolved leaf: which driver installs it, the component name, and the concrete
    package identifier; its `key` is `driver\\component` (the unit key). `deps` are the unit keys
    it depends on; `requested_as` are the roots that pulled it.'''

    def __init__(self, driver, component, package):
        self.driver = driver
        self.component = component
        self.package = package
        self.via = None         # the winning binding's `via:` (maps binding-level floors to the unit)
        self.binding = None     # the winning Binding itself (several may share a via: binding_of)
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

    def __repr__(self):
        return f'Unit({self.key} -> {self.package!r})'


# Default order for choosing among genuinely-alternative install methods (same context, no
# most-specific winner). A machine may replace this globally (config `driver-preference:`) or an
# OS block may override it (`driver-preference:` in the os: layer). Native-first is conventional.
# The lists form a fallback chain (_effective_preference): OS-block lists, then the setting, then
# this default, each adding only the drivers the earlier ones don't name — so only a driver named in
# NO list is least-preferred, and those tie among themselves (a tie is an error, not a guess).
# brew ranks just ahead of tarball: an ordinary method (gated to glibc by its `drivers:` block) that
# beats a hand-rolled download, never a native/flatpak/snap/.deb/AppImage one.
DEFAULT_DRIVER_PREFERENCE = ['native', 'aur', 'flatpak', 'snap', 'native-pkg-file', 'appImage',
                             'brew', 'tarball', 'source', 'script']


def binding_pin(pins, name):
    '''The binding-pin (a via) `pins:` sets for component `name`, or None. A value that names a
    PROVIDER instead (`jdk: jdk-25` — jdk is a component AND the capability jdk-25 provides) is a
    provider-pin for consumers, never a method filter on the component itself (B15 / routing-06).'''
    v = (pins or {}).get(name)
    return v if v is not None and str(v) in pin_via_names() else None


def disabled_driver(binding, context):
    '''The `disabled-drivers:` entry that turns `binding` off here — its own via, or for `via:
    native` this OS's native manager (`disabled-drivers: [ brew ]` on Fedora Atomic covers every
    native binding too — B15 / routing-05) — else None.'''
    disabled = getattr(context, 'disabled', None) or ()
    if binding.via in disabled:
        return binding.via
    if binding.via == 'native':
        native = getattr(context, 'native_driver', None)
        if native and native in disabled:
            return native
    return None


def _matching(component, context, pins):
    '''(the CANDIDATE bindings in this context, the binding-pin or None). A binding-pin filters to
    that via first; then a binding is a candidate when its driver isn't disabled, it isn't `via:
    native` on a native-less OS, no driver gate (explicit or derived) closes it, the trust gate lets
    it through (trustgate.gated), it covers this cpu (arch_ok) and its `when:` holds — every one a
    validity filter; not_candidate_reason words them in this order.'''
    bindings = component.bindings
    pin = binding_pin(pins, component.name)
    if pin is not None:                     # binding-pin: force this method, still context-valid
        bindings = [b for b in bindings if b.via == pin]
        if not bindings:
            raise ResolveError(f'{component.name}: pinned to via:{pin!r}, which is not a binding',
                               'pin-unrealizable')
    # a DISABLED driver (machine `disabled-drivers:` setting) makes its bindings non-matching here,
    # exactly like a false `when:` — so a component whose only method is via it becomes unroutable
    # (a `suggests:` skips it silently, a hard `requires:`/explicit want errors honestly).
    cpu = getattr(context, 'cpu', None)
    # an OS with no system package manager (KDE Linux): `via: native` can't work there, so it isn't a
    # candidate — the component falls through to flatpak/tarball/cargo/… instead of erroring
    no_native = not getattr(context, 'has_native', True)
    return [b for b in bindings
            if disabled_driver(b, context) is None and not (no_native and b.via == 'native')
            and driver_gated(b, context) is None and trustgate.gated(b, context) is None
            and arch_ok(b.details, cpu) and b.pred.eval(context)], pin


def driver_gated(binding, context):
    '''The driver whose gate is closed in this context and so makes `binding` not a
    candidate — its own via, or (for `via: native`) this OS's native manager — else None. A
    validity-only filter, like a false `when:` / `cpu-names:`: it never adds specificity, so it
    never shifts which method is the default where the driver IS valid. (`gated_drivers` holds the
    explicit gates OsCascade.context evaluates plus the derived ones gated_context adds — a driver
    whose own requires: can't be met here; a hand-built Context has none.)'''
    gated = getattr(context, 'gated_drivers', None)
    if not gated:
        return None
    if binding.via in gated:
        return binding.via
    if binding.via == 'native':
        native = getattr(context, 'native_driver', None)
        if native in gated:
            return native
    return None


def driver_gate_reason(binding, cascade, context):
    '''Human text for why `binding` is not a candidate because of a driver gate — e.g. "the brew
    driver isn't valid here (drivers: brew when: glibc_linux)", or for a DERIVED gate "the snap
    driver can't work here: nothing provides "snapd" here (required by snapd-socket)" — or None (not
    gated out here).'''
    untrusted = trustgate.gated(binding, context)
    if untrusted is not None:
        return (f'it comes from an untrusted plugin layer and {untrusted} — review the plugin, '
                'then `configsys plugin trust`')
    drv = driver_gated(binding, context)
    if drv is None:
        return None
    via_note = ' — this OS\'s native manager' if binding.via == 'native' else ''
    derived = (getattr(context, 'derived_gates', None) or {}).get(drv)
    if derived is not None:
        return f"the {drv} driver{via_note} can't work here: {derived}"
    text = (getattr(cascade, 'driver_gates', None) or {}).get(drv, ('?',))[0]
    return f"the {drv} driver{via_note} isn't valid here (drivers: {drv} when: {text})"


def not_candidate_reason(binding, cascade, context, pin=None):
    '''Why `binding` is NOT a candidate here, in _matching's own order — your binding-pin names
    another method, its driver is disabled, `via: native` on an OS with no package manager, a
    driver gate (driver_gate_reason), this cpu missing from its `cpu-names:` / cpu-keyed `asset:`,
    or its `when:` — or None when it is a candidate. The text `where` prints, so every method it
    rules out says why.'''
    if pin is not None and binding.via != pin:
        return f'you pinned via:{pin}'
    off = disabled_driver(binding, context)
    if off is not None:
        note = ' — this OS\'s native manager' if binding.via == 'native' else ''
        return f'the {off} driver{note} is disabled here (disabled-drivers:)'
    if binding.via == 'native' and not getattr(context, 'has_native', True):
        return "this OS has no package manager, so `via: native` can't work here"
    gate = driver_gate_reason(binding, cascade, context)
    if gate:
        return gate
    cpu = getattr(context, 'cpu', None)
    if not arch_ok(binding.details, cpu):
        cpus = cpu_names(binding.details) or _asset_cpus(binding.details) or ()
        return f"{cpu} isn't among the cpus it ships for ({', '.join(sorted(cpus))})"
    if not binding.pred.eval(context):
        return '`when:` is false here'
    return None


# -- derived driver gates: a driver is valid only where its own `requires:` can be met ----------

def gated_context(cascade, components, drivers, block, version=None, cpu=None, disabled=(),
                  pins=None, overrides=None, preference=None, never_auto_drivers=None):
    '''This machine's predicate context with EVERY driver gate applied: the explicit `drivers:`
    `when:` gates (OsCascade.context) plus the DERIVED ones — a driver whose own `requires:` can't be
    met here is not valid here, so none of its bindings is a candidate (snap where snapd has no
    method, appImage on musl without a `glibc` provider, flatpak where flatpak can't install).

    Computed as a greatest fixpoint with the real resolver: start with every non-explicitly-gated
    driver valid, try to satisfy each driver's requires in a scratch _State, gate the ones that fail,
    and repeat until nothing changes (gating a driver can only make more requirements fail, so it
    terminates). `pins` are honored, so a provider-pin enables a never-auto provider — e.g.
    `pins: { glibc: gcompat }` makes appImage valid on Alpine. Callers pass only the HARD pins (yours
    + auto-tighten), never the detection tier's soft ones, so enabling a never-auto provider stays
    explicit. The reasons land in `ctx.derived_gates` ({driver: why}) for `where`. Cached on the cascade per (components,
    drivers, context, pins, …); a context is never mutated after it's returned.'''
    if block not in cascade.blocks:            # an unknown forced block: say so, never an empty lineage
        from .osdetect import unknown_block_message
        raise ConfigsysError(unknown_block_message(block, cascade.blocks))
    pins = dict(pins or {})
    key = (id(components), id(drivers), id(overrides), block, version, cpu,
           frozenset(disabled or ()), frozenset((k, str(v)) for k, v in pins.items()),
           tuple(preference or ()), frozenset(never_auto_drivers or ()))
    cache = cascade.__dict__.setdefault('_gated_ctx_cache', {})
    hit = cache.get(key)
    # the entry HOLDS the keyed objects, and a hit must be them: an id() is reused once its object is
    # gone, so a transient dict must never inherit another one's answer (routing-37)
    if hit is not None and hit[0] is components and hit[1] is drivers and hit[2] is overrides:
        return hit[3]
    ctx = cascade.context(block, version, cpu, disabled or ())
    explicit = frozenset(getattr(ctx, 'gated_drivers', ()) or ())
    derived = {}
    shared = None                      # the per-load indexes every scratch _State would rebuild
    while True:
        ctx.gated_drivers = explicit | frozenset(derived)
        new = {}
        for drv in sorted(drivers):
            caps = drivers[drv]
            if not caps or drv in ctx.gated_drivers or drv in getattr(ctx, 'disabled', ()):
                continue
            st = _State(cascade, components, drivers, ctx, pins, overrides or {}, preference,
                        never_auto_drivers, shared=shared)
            shared = shared or (st.providers, st.never_auto)
            try:
                for cap in caps:
                    st._satisfy(cap, None, f'the {drv} driver', f'the {drv} driver')
                st.drain()
            except AmbiguityError:
                # two equal providers of the driver's tool is YOUR decision, not "can't work here":
                # the driver stays valid, and each pick through it reports the ambiguity with its fix
                # (a provider-pin / `standing:`) instead of reading `dangling` (B15 / routing-11)
                pass
            except ResolveError as e:
                new[drv] = str(e)
        if not new:
            break
        derived.update(new)
    ctx.derived_gates = derived
    cache[key] = (components, drivers, overrides, ctx)
    return ctx


def untrusted_plugin(binding):
    '''The plugin a binding's layer file belongs to — its checkout's dir name, which is what
    `configsys plugin trust <name>` takes (a data file may sit in a subdir of the checkout).'''
    from .layers import _plugin_tree
    src = getattr(binding, 'source', None)
    return os.path.basename(_plugin_tree(src)) if src else '?'


def _gate_note(component, context, pin):
    '''" — <via>: <why>" for each of `component`'s bindings a driver gate removed here (the bindings
    otherwise valid), so "no binding here" names the reason instead of leaving you to guess.'''
    cpu = getattr(context, 'cpu', None)
    notes = {}
    for b in component.bindings:
        if pin is not None and b.via != pin:
            continue
        off = disabled_driver(b, context)
        if off is not None and b.via not in notes and arch_ok(b.details, cpu) and b.pred.eval(context):
            notes[b.via] = f'the {off} driver is disabled here (disabled-drivers:)'
            continue
        untrusted = trustgate.gated(b, context)
        if untrusted is not None and b.via not in notes and arch_ok(b.details, cpu) \
                and b.pred.eval(context):
            plug = untrusted_plugin(b)
            notes[b.via] = (f'from the untrusted plugin layer {plug} '
                            f'— {untrusted} (review it, then `configsys plugin trust {plug}`)')
            continue
        drv = driver_gated(b, context)
        if drv is None or b.via in notes or not (arch_ok(b.details, cpu) and b.pred.eval(context)):
            continue
        why = (getattr(context, 'derived_gates', None) or {}).get(drv)
        notes[b.via] = (f'the {drv} driver can\'t work here ({why})' if why is not None
                        else f'the {drv} driver isn\'t valid here')
    return ''.join(f'; {v}: {n}' for v, n in notes.items())


def cpu_names(details):
    '''A binding's `cpu-names:` map {cpu: upstream token}, or None. Upstreams spell CPUs their own
    way (amd64/arm64/x64/linux64…), so `$ARCH` expands through this map — and its KEYS are the CPUs
    upstream ships: on any other cpu the binding is not valid (like a false `when:`, but without
    making the binding more specific, so it never shifts which method is the default).'''
    m = details.get('cpu-names') if isinstance(details, dict) else None
    return m if isinstance(m, dict) and m else None


def _asset_cpus(details):
    '''The cpus an explicit per-cpu `asset:` map covers ({x86_64: …} or format-then-cpu
    {deb: {x86_64: …}}), or None when the asset isn't cpu-keyed.'''
    a = details.get('asset') if isinstance(details, dict) else None
    if not isinstance(a, dict) or not a:
        return None
    inner = [v for v in a.values() if isinstance(v, dict)]
    return set().union(*inner) if inner else set(a)


def arch_ok(details, cpu):
    '''False when the binding declares the cpus it supports — via `cpu-names:` keys, or an explicit
    per-cpu `asset:` map — and this cpu isn't among them. An undetected cpu (None) never declines.'''
    if cpu is None:
        return True
    m = cpu_names(details)
    if m is not None and cpu not in m:
        return False
    cpus = _asset_cpus(details)
    return cpus is None or cpu in cpus


def arch_token(details, cpu):
    '''What `$ARCH` expands to for this cpu: the binding's `cpu-names:` entry, else the cpu itself.'''
    m = cpu_names(details)
    return str(m.get(cpu, cpu)) if m and cpu else cpu


def candidate_bindings(component, cascade, context, pins=None):
    '''Every candidate binding for this context (_matching's filters: `when:`, cpu, disabled
    drivers, driver and trust gates; a binding-pin in `pins` narrows to its via) — the honest set of
    install methods available here, for the picker / `where` introspection. `when:` is validity
    only: this never narrows the set to force one winner. In binding order.'''
    return _matching(component, context, pins)[0]


NEVER_AUTO = 'never-auto'   # a binding/provider that is valid + listed + pinnable, but never the auto-default


def _standing(spec):
    '''The `standing:` of a binding/driver/component spec — the ONE preference knob:
      * `never-auto` -> valid + offered, but never the auto-default while an ordinary method is valid
        (a binding/driver method never wins the default; a component-provider is never auto-pulled);
      * an INTEGER   -> a preference rank, higher wins;
      * None         -> normal.
    `spec` is any dict carrying the key (a binding's details, an os `drivers:` block, or a component
    spec).'''
    s = spec.get('standing')
    if s is None:
        return None
    st = str(s).strip().lower()
    if st == NEVER_AUTO:                               # (the undocumented 'candidate'/'never' aliases: retired)
        return NEVER_AUTO
    try:
        return int(st)
    except ValueError:
        return None


def standing_problem(spec):
    '''Why `spec`'s `standing:` means nothing, or None (absent, `never-auto`, or an integer) — a
    value _standing reads as "normal" without a word, so `check` says it (`bad-standing`).'''
    if not isinstance(spec, dict) or spec.get('standing') is None or _standing(spec) is not None:
        return None
    return (f'`standing: {spec["standing"]}` is neither `never-auto` nor an integer rank — it is '
            f'ignored (read as no standing)')


def _prefer_rank(binding):
    '''The binding's `standing:` preference rank (higher wins), default 0. A `never-auto` binding has
    no rank (it's excluded from the auto-default pool anyway).'''
    s = _standing(binding.details)
    return s if isinstance(s, int) else 0


def _binding_never_auto(binding):
    '''True if this binding is `standing: never-auto`: offered / listed / pinnable, but never the
    auto-default while an ordinary method is valid — so a validity-gated method (a debian-only vendor
    `.deb`) can be available without beating a broad method (a universal flatpak) by specificity.'''
    return _standing(binding.details) == NEVER_AUTO


def _effective_preference(cascade, context, preference):
    '''The driver-preference order for this context, as a FALLBACK CHAIN: the OS blocks'
    `driver-preference:` lists walking the lineage (nearest first), then the passed-in global
    (config) list, then the built-in DEFAULT_DRIVER_PREFERENCE. Each later list contributes only the
    drivers the earlier ones don't name, in its own order — so a list fully decides every driver it
    names, and one written before a driver existed still ranks that driver (by the default) instead
    of leaving it tied last with every other unlisted one. Only drivers named in NO list tie.'''
    chain = [as_list(pref) for name in context.lineage
             if (pref := (cascade.blocks.get(name) or {}).get('driver-preference'))]
    if preference:
        chain.append(list(preference))
    chain.append(DEFAULT_DRIVER_PREFERENCE)
    order = []
    for lst in chain:
        order += [d for d in lst if d not in order]
    return order


def _most_specific_binding(matching, cascade):
    '''The unique binding whose `when:` is ⊆ every other matching binding's, or None when the
    candidates are incomparable OR several share the most-specific `when:` (genuine alternatives —
    the preference channel decides those). Operates over bindings, not deduped predicates, so two
    same-`when:` different-`via:` bindings are correctly seen as a tie, not silently collapsed.'''
    # memoized per load: the answer depends only on the bindings' `when:`s and the OS tree, never on
    # the machine context — and the same pools recur across every resolve (and gated_context's
    # scratch resolutions), each costing a pairwise predicate.subset sweep
    key = tuple(matching)
    cache = cascade.__dict__.setdefault('_most_specific_cache', {})
    if key not in cache:
        mins = [b for b in matching
                if all(predicate.subset(b.pred, o.pred, cascade) for o in matching)]
        cache[key] = mins[0] if len(mins) == 1 else None
    return cache[key]


def via_representatives(matching, cascade):
    '''One binding per via — the one that RESOLVES when that via is pinned: its most-specific
    `when:` among the via's valid bindings. The picker and pins choose a VIA (1:1 with a driver),
    so same-via siblings collapse to this representative; a shadowed same-via binding (e.g.
    fastfetch's bare `via: native` behind its `when: debian` .deb binding) is not separately
    reachable. Same-via valid bindings are guaranteed comparable (incomparable = a routecheck load
    error), so the representative is unique. Preserves first-seen via order.'''
    by_via = {}
    for b in matching:
        by_via.setdefault(b.via, []).append(b)
    return [g[0] if len(g) == 1 else (_most_specific_binding(g, cascade) or g[0])
            for g in by_via.values()]


def _by_preference(matching, component, cascade, context, preference):
    '''Pick among incomparable/equally-specific candidates via the preference channel — separate
    from `when:`. Order: explicit `standing:` rank (higher wins), then driver-preference index. A
    true tie is a ResolveError that points at the preference channel, NEVER at narrowing `when:`.'''
    order = _effective_preference(cascade, context, preference)

    def key(b):
        return (-_prefer_rank(b), order.index(b.via) if b.via in order else len(order))

    ranked = sorted(matching, key=key)
    best = ranked[0]
    if key(ranked[1]) == key(best):
        tied = sorted({b.via for b in ranked if key(b) == key(best)})
        raise ResolveError(
            f'{component.name}: install methods {tied} are equally valid AND equally preferred '
            f'here — set a `driver-preference` order or a per-binding `standing:` rank to choose one '
            f'(do not narrow `when:`: every one of these methods genuinely works here)', 'method-tie')
    rule = 'standing:' if _prefer_rank(best) != _prefer_rank(ranked[1]) else 'driver-preference'
    return best, rule


def _select(component, cascade, context, pins=None, preference=None, never_auto_drivers=None):
    '''-> (winning Binding, [all candidates], rule). Candidates = _matching's (validity only). The
    default among them: drop the never-auto methods (unless all are), then the single most-specific
    `when:`, else the preference channel among the minimal ones (`standing:` rank, then
    driver-preference). `rule` names the deciding step ('only method here', 'only ordinary method
    here', 'most-specific when:', 'standing:', 'driver-preference'). Raises ResolveError if nothing
    is valid or the choice is undecidable. Resolver.select wraps this as a Selection.

    `never_auto_drivers` (a set of via/driver names, e.g. {'snap'}, from `standing: never-auto` on a
    `drivers:` block) marks methods that are valid and LISTED but never win the AUTO-default while
    any ordinary method is valid here — so a low-preference method that may be narrowly gated (a
    snap binding with a `when:` that would otherwise beat a broad native binding by specificity) can
    be offered without hijacking the default. A binding may ALSO carry `standing: never-auto` itself (e.g. a
    debian-only vendor `.deb` that should stay a candidate under a universal flatpak). A binding-pin
    still forces such a method (it filters `matching` to that via upstream); and if EVERY valid
    method here is never-auto, they compete among themselves normally. The candidate list returned is
    ALWAYS the full `matching` set, so the picker/`where` still show the never-auto methods.'''
    matching, pin = _matching(component, context, pins)
    if not matching:
        extra = f' (pinned to via:{pin!r})' if pin is not None else ''
        note = _gate_note(component, context, pin)
        raise ResolveError(f'no binding for {component.name} in this context{extra}{note}',
                           'gated' if note else 'no-candidate')
    if len(matching) == 1:
        return matching[0], matching, 'only method here'
    excluded = never_auto_drivers or frozenset()
    # a `drivers:` block describes the MANAGER, whichever via label reached it: a never-auto block on
    # this OS's native manager (e.g. `brew`) covers its `via: native` bindings too.
    native_drv = cascade.native(context.lineage[0]) if (excluded and context.lineage) else None
    pool = [b for b in matching
            if b.via not in excluded and not (b.via == 'native' and native_drv in excluded)
            and not _binding_never_auto(b)] or matching
    if len(pool) == 1:
        return pool[0], matching, 'only ordinary method here'
    ms = _most_specific_binding(pool, cascade)
    if ms is not None:
        return ms, matching, 'most-specific when:'
    # no unique narrowest: preference decides among the MINIMAL ones only — a binding strictly
    # broader than another candidate never beats it, so adding an offered method can't flip the
    # default between two others (routing-23; principles.md: specificity before preference)
    minimal = _minimal_bindings(pool, cascade)
    if len(minimal) == 1:
        return minimal[0], matching, 'most-specific when:'
    winner, rule = _by_preference(minimal, component, cascade, context, preference)
    return winner, matching, rule


def _minimal_bindings(pool, cascade):
    '''The bindings of `pool` no other one is STRICTLY inside (`when:` ⊂, not ≡) — the narrowest
    alternatives, in pool order. Never empty (a finite pool has a minimal element).'''
    def strictly_inside(o, b):
        return predicate.subset(o.pred, b.pred, cascade) and not predicate.subset(b.pred, o.pred, cascade)
    return [b for b in pool if not any(o is not b and strictly_inside(o, b) for o in pool)] or pool


def select_binding(component, cascade, context, pins=None, preference=None, never_auto_drivers=None):
    '''The one binding that resolves here (the default method). See _select.'''
    return _select(component, cascade, context, pins, preference, never_auto_drivers)[0]


def _driver(binding, cascade, block):
    if binding.via == 'native':
        drv = cascade.native(block)
        if drv is None:
            raise ResolveError(f'no native package manager on {block}', 'no-candidate')
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
    if binding.via in ('dotfiles', 'glue'):
        return None                     # a dotfile / glue snippet has no package
    # appImage / deb / tarball / crate / font: the display/dist name
    return binding.details.get('name') or component.name


# keys that steer resolution, not installation — never handed to a driver.
_RESOLVER_KEYS = ('requires', 'suggests', 'parts', 'app', 'standing', 'provides')   # never a driver field


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
        return asset.replace('$ARCH', arch_token(binding.details, cpu))
    return asset


def binding_of(component, rc):
    '''The binding of `component` a resolved unit `rc` came from: the one that WON selection
    (`rc.binding`, carried from resolution). Several bindings may share a `via:` (`native` per OS,
    a `when:`-split download), so "the first with that via" is not it. For an rc built without one
    (an install receipt, a hand-built unit) it falls back to the same-via binding whose install
    fields match rc's, else the first of that via — or None.'''
    b = getattr(rc, 'binding', None)
    if b is not None:
        return b
    same = [b for b in component.bindings if b.via == (rc.via or None)]
    if len(same) > 1:
        exact = [b for b in same if _install_fields(b.details, rc.name) == rc.fields]
        if exact:
            return exact[0]
    return same[0] if same else None


def unit_for_binding(component, binding, cascade, block, overrides=None):
    '''Build the Unit a SPECIFIC binding would produce — for per-method introspection (the
    `versions` view: what each install method offers), independent of which one wins. Mirrors the
    worklist's single-binding construction (driver + name-map/override + install fields); does NOT
    close requires. Returns None for an aggregator (`parts`) or a component-names drop.'''
    if binding.via == 'parts':
        return None
    drv = _driver(binding, cascade, block)
    override, drop = _name_override(overrides or {}, drv, component.name)
    if drop:
        return None
    package = override if override is not _NO_OVERRIDE else _package(binding, drv, component)
    unit = Unit(drv, component.name, package)
    unit.via = binding.via
    unit.binding = binding
    unit.details = _install_fields(binding.details, unit.package)
    unit.source = binding.source or component.source
    return unit


# -- full resolution: the worklist to a fixpoint ---------------------------

def resolve(names, cascade, components, drivers, block, version=None, cpu=None, pins=None,
            overrides=None, preference=None, never_auto_drivers=None, disabled=None):
    '''Resolve component names (picks, or an op's names) to the full unit closure for a context.
    Strict: the first ResolveError raises (resolve_resilient collects them per pick instead).

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
                         overrides, preference, never_auto_drivers, disabled)[0]


def resolve_roots(names, cascade, components, drivers, block, version=None, cpu=None, pins=None,
                  overrides=None, preference=None, never_auto_drivers=None, disabled=None,
                  soft=None, dropped_out=None):
    '''Like resolve(), but also return the set of unit keys bound *directly* by the named
    components (a named parts-component contributes its parts' keys; driver/driver deps
    are not roots). The app applies the requested op to these, and expand_plan folds in deps.
    `soft` / `dropped_out` as in resolve_resilient (the detection tier's adopt-installed pins).'''
    hard = {k: v for k, v in (pins or {}).items() if k not in (soft or ())}   # soft pins never open a gate
    ctx = gated_context(cascade, components, drivers, block, version, cpu, disabled, hard,
                        overrides, preference, never_auto_drivers)
    st = _State(cascade, components, drivers, ctx, pins or {}, overrides or {}, preference,
                never_auto_drivers, soft=soft, dropped=dropped_out)
    roots = set()
    for name in names:
        roots |= st.add_component(name, root=name)  # phase 1: wants + their provides
    st.drain()                                      # phase 2: close requirements
    st.propagate_requested()
    return st.units, roots


def resolve_resilient(names, cascade, components, drivers, block, version=None, cpu=None,
                      pins=None, overrides=None, preference=None, never_auto_drivers=None, disabled=None,
                      soft=None, dropped_out=None, provider_rules_out=None, skipped_parts_out=None,
                      kinds_out=None):
    '''Resilient resolution for the inspect/TUI pipeline: a requested name that can't resolve
    (unknown, no binding here, or an unsatisfiable requirement) is collected into `errors`
    instead of aborting the whole set — everything resolvable still resolves. Returns
    (units, errors) with errors = {requested_name: message}. So one broken pick (e.g. a
    component from a malformed plugin) is an error row and can't brick the tool; a unit whose hard
    requirement failed is pruned with everything that hard-depends on it (_prune_failed).

    `soft` names the `pins` keys that are SOFT (the detection tier's adopt-installed pins): such a
    pin is honored when it can be, but one that can't (its provider fails a version constraint, or
    its method/provider isn't valid here) is DROPPED for that edge and normal selection proceeds —
    never an error. `dropped_out` (a dict) collects {pin key: why it was dropped};
    `provider_rules_out` (a dict) collects {cap: the rule that picked its auto provider};
    `kinds_out` (a dict) {requested_name: the ResolveError kind behind its error} (KINDS).'''
    hard = {k: v for k, v in (pins or {}).items() if k not in (soft or ())}   # soft pins never open a gate
    ctx = gated_context(cascade, components, drivers, block, version, cpu, disabled, hard,
                        overrides, preference, never_auto_drivers)
    st = _State(cascade, components, drivers, ctx, pins or {}, overrides or {}, preference,
                never_auto_drivers, soft=soft, dropped=dropped_out)
    errors = {}
    kinds = kinds_out if kinds_out is not None else {}
    root_keys = {}
    for name in names:
        try:
            root_keys[name] = st.add_component(name, root=name)
        except ResolveError as e:
            errors[name] = str(e)
            kinds[name] = e.kind
    st.drain(errors=errors, kinds=kinds)
    if st.failed_keys:
        _prune_failed(st, root_keys, errors, kinds)
    st.propagate_requested()
    if provider_rules_out is not None:
        provider_rules_out.update(st.provider_rules)
    if skipped_parts_out is not None:
        skipped_parts_out.update(st.skipped_parts)
    return st.units, errors


def _prune_failed(st, root_keys, errors=None, kinds=None):
    '''A unit whose HARD requirement failed can't be installed — so leave nothing of it installable.
    The failure can come AFTER the unit was added (a pinned provider that can't meet a version floor:
    blender-5.2's cuda-toolkit >=12.8 vs a cuda-toolkit -> cuda-toolkit-11 pin), and that half-resolved
    unit — its requirement silently missing — used to reach the TUI as installable and run a doomed
    build. Drop the failed units and everything that HARD-depends on them; a parent that merely
    SUGGESTS one keeps going without it (btop stays when btop-glue can't resolve). Then keep only what
    the surviving requested roots still reach — units pulled in solely for a dropped one go too.'''
    gone = set(st.failed_keys)
    changed = True
    while changed:                                        # hard dependents of a failed unit fail too
        changed = False
        for key in st.units:
            if key not in gone and st.hard_deps.get(key, set()) & gone:
                gone.add(key)
                changed = True
    live, stack = set(), [k for keys in root_keys.values() for k in keys if k not in gone]
    while stack:
        key = stack.pop()
        if key in live or key in gone or key not in st.units:
            continue
        live.add(key)
        stack.extend(st.units[key].deps)
    st.units = {k: u for k, u in st.units.items() if k in live}
    if errors is not None:
        # a pick whose OWN unit went with a shared failed dependency gets its error row too — it used to
        # vanish without one when an earlier pick had already queued (and reported) that edge (B5)
        for name, keys in root_keys.items():
            if name in errors or not keys or any(k in live for k in keys):
                continue
            cause = next((st.failure_of[k] for k in sorted(gone) if k in st.failure_of), 'a dependency')
            errors[name] = f'needs something that can\'t be installed here: {cause}'
            if kinds is not None:
                kinds[name] = 'unmet-require'
    for u in st.units.values():
        u.deps = u.deps - gone                            # a dropped soft companion isn't a dep


def provider_standing(components):
    '''-> rank(name): a provider component's integer `standing:` (higher wins; 0 when unset or
    `never-auto`). Orders candidate providers of a capability in resolve._State._pick_provider.'''
    def rank(name):
        return getattr(components.get(name), 'standing_rank', 0) or 0
    return rank


def _bindable(component, cascade, ctx, pins, preference=None, never_auto_drivers=None):
    try:
        select_binding(component, cascade, ctx, pins, preference, never_auto_drivers)
        return True
    except ResolveError:
        return False


_INDEX_CACHE = {}                        # id(components) -> (components, providers, never_auto)


def _component_indexes(components):
    '''(providers {cap: [component names]}, never-auto set) for a loaded component set — built once
    per set (keyed by identity, holding the set so the id can't be reused while cached). Read-only
    for every _State.'''
    hit = _INDEX_CACHE.get(id(components))
    if hit is not None and hit[0] is components:
        return hit[1], hit[2]
    providers = {}
    for name, comp in components.items():
        for cap in set(comp.provides) | {name}:         # a component always provides its own name
            providers.setdefault(cap, []).append(name)
    never_auto = {n for n, c in components.items() if getattr(c, 'never_auto', False)}
    if len(_INDEX_CACHE) > 16:
        _INDEX_CACHE.clear()
    _INDEX_CACHE[id(components)] = (components, providers, never_auto)
    return providers, never_auto


class _State:
    def __init__(self, cascade, components, drivers, ctx, pins, overrides=None, preference=None,
                 never_auto_drivers=None, soft=None, dropped=None, shared=None):
        self.cascade = cascade
        self.components = components
        self.drivers = drivers
        self.ctx = ctx
        self.pins = pins
        # SOFT pin keys (detected-installed adoption): honored when possible, dropped — never an
        # error — when they can't be (see _select_binding / _satisfy). `dropped` records why.
        self.soft = frozenset(soft or ())
        self.dropped = dropped if dropped is not None else {}
        self.skipped_parts = {}             # {bundle: [(part, why)]} parts with no route here (B15)
        self.provider_rules = {}           # cap -> the rule that picked its auto provider (explain/where)
        self.preference = preference       # driver-preference order (config global); None = built-in
        self.never_auto_drivers = never_auto_drivers or frozenset()   # vias never auto-defaulted (e.g. snap)
        self.overrides = overrides or {}   # {driver: {component: pkg-or-drop}} (component-names)
        self.block = ctx.lineage[0]
        self.units = {}
        self.hard_deps = {}                # unit key -> keys it HARD-requires (not suggests)
        self.failed_keys = set()           # units whose hard requirement failed (resilient mode)
        self.failure_of = {}               # failed unit key -> the error (B5: shared by later picks)
        # capability -> frozenset of unit keys satisfying it (empty = the environment
        # provides it, no unit needed).
        self.inventory = {cap: frozenset() for cap in cascade.provides(self.block)}
        # version-scoped residency (Phase 2): the DEFAULT (unconstrained) resident per cap stays in
        # `inventory`; `resident_version` records its provided version so a later CONSTRAINED require
        # can test it, and `constrained` caches a distinct resident per (cap, constraint) so two
        # consumers wanting different versions coexist. Empty/untouched for unversioned caps -> the
        # unconstrained path is byte-identical (the golden).
        self.resident_version = {}                 # cap -> provided version of the default resident
        self.constrained = {}                      # (cap, constraint) -> frozenset(keys)
        # `shared` = (providers, never_auto) from a sibling _State over the same components (gated_context
        # runs many scratch resolutions) — both depend only on `components`, so reuse them
        # Without one, the pair is cached per loaded component set (C3: rebuilding the provider index
        # from all ~830 components was 81% of a single-name resolve — `where`, coverage, the golden).
        if not shared:
            shared = _component_indexes(components)
        self.providers = shared[0]
        # never-auto providers are never AUTO-pulled to close a requirement — only used when the
        # component is explicitly wanted (then it's in inventory before we look for candidates)
        # or named by a provider-pin. Keeps a best-effort shim (gcompat) from installing itself.
        self.never_auto = shared[1]
        self.via_names = pin_via_names()           # for binding-vs-provider pin classification
        self.queue = deque()                       # (req_key, req_name, cap, constraint, root, optional)
        # each component's selection, ONCE per resolution: it depends only on the component under this
        # state's fixed pins / context / preference, and _is_bindable asks it of every candidate
        # provider before add_component asks again (routing-36). {name: (binding, None) | (None, error)}
        self._selected = {}

    def _provider_index(self):
        return _component_indexes(self.components)[0]

    def add_component(self, name, root):
        '''Resolve a component name -> the frozenset of unit keys it contributes.'''
        if name not in self.components:
            raise ResolveError(f'unknown component: {name}', 'unknown')
        comp = self.components[name]
        # a component with NO bindings is "removed" (a user override `{}`): it contributes
        # nothing and is a no-op when named directly. This differs from a component that HAS
        # bindings but none match the context (select_binding below errors "no binding here").
        if not comp.bindings:
            return frozenset()
        binding = self._select_binding(comp)

        # a `via: parts` binding is a pure aggregator: no unit of its own, just the
        # union of its (recursively resolved) parts, each attributed to this root.
        if binding.via == 'parts':
            stack = self.__dict__.setdefault('_parts_stack', [])
            if name in stack:                          # a parts cycle: an error row, never a crash (B4)
                raise PartsCycleError('parts cycle: ' + ' -> '.join(stack[stack.index(name):] + [name]))
            stack.append(name)
            try:
                keys, skipped = set(), []
                parts = as_list(binding.details.get('parts'))
                for part in parts:
                    # a part with no route here is SKIPPED with a notice — the bundle is the union of
                    # what routes here, like `profile:` expansion (B15 / routing-08); a cycle is not
                    try:
                        keys |= self.add_component(part, root)
                    except PartsCycleError:
                        raise
                    except ResolveError as e:
                        skipped.append((part, str(e)))
            finally:
                stack.pop()
            if skipped:
                if len(skipped) == len(parts):
                    raise ResolveError(f'no part of {name} installs here: '
                                       + '; '.join(f'{p}: {why}' for p, why in skipped), 'no-candidate')
                self.skipped_parts.setdefault(name, []).extend(skipped)
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
        unit.via = binding.via
        unit.binding = binding
        unit.requested_as = {root}
        unit.details = _install_fields(binding.details, unit.package)
        # the layer that DEFINED this binding (content roots for dotfiles follow it even across an
        # additive amend); falls back to the component's top layer for directly-built components.
        unit.source = binding.source or comp.source
        self.units[key] = unit
        for cap in set(comp.provides) | {name}:
            if cap not in self.inventory:                          # first provider = the default resident
                self.inventory[cap] = frozenset({key})
                self.resident_version[cap] = comp.prov_versions.get(cap)
        # requires (HARD): method-independent (component) + driver-level + binding-specific. Each
        # edge carries its version CONSTRAINT (or None) so a versioned `requires: {cap: ">=12"}`
        # selects a resident by version. A component's config is just another required component
        # (a `via: dotfiles` one), so it flows through here too.
        # the binding's constraints INCLUDING any `version-floors:` patch (routes._apply_version_floors
        # writes them to req_versions) — a patched floor applies at component and binding level alike (B15)
        bind_cons = dict(getattr(binding, 'req_versions', None)
                         or cap_constraints(binding.details.get('requires')))
        # driver-level requires are keyed by the DRIVER that installs the unit: a `via: native`
        # binding reaches the OS's manager (`drv` — apt/dnf/brew/…), so that manager's `drivers:` block
        # applies too (fedora_atomic's native brew requires homebrew).
        drv_reqs = list(self.drivers.get(binding.via, []))
        if binding.via == 'native' and drv != binding.via:
            drv_reqs += [c for c in self.drivers.get(drv, []) if c not in drv_reqs]
        reqs = ([(cap, comp.req_versions.get(cap)) for cap in comp.requires]
                + [(cap, None) for cap in drv_reqs]
                + [(cap, bind_cons.get(cap)) for cap in cap_names(binding.details.get('requires'))])
        for cap, con in reqs:
            self.queue.append((key, name, cap, con, root, False))
        # suggests (SOFT): pulled in if resolvable in the loaded layers, skipped silently if not.
        # A suggested component's OWN requires stay hard once it is pulled. (Suggests are unversioned.)
        for cap in list(comp.suggests) + cap_names(binding.details.get('suggests')):
            self.queue.append((key, name, cap, None, root, True))
        return frozenset({key})

    def _select_binding(self, comp):
        '''select_binding under this resolution's pins — but a SOFT (detected) pin on `comp` that
        can't be honored here (names a method not valid on this machine) is ignored for it, falling
        through to the normal default, instead of erroring. Memoized per state (`_selected`).'''
        hit = self._selected.get(comp.name)
        if hit is None:
            try:
                hit = (self._select_binding_uncached(comp), None)
            except ResolveError as e:
                hit = (None, e)
            self._selected[comp.name] = hit
        if hit[1] is not None:
            raise hit[1].with_traceback(None)          # (a fresh traceback each time, never a growing one)
        return hit[0]

    def _select_binding_uncached(self, comp):
        soft_pinned = comp.name in self.soft and comp.name in self.pins
        try:
            b = select_binding(comp, self.cascade, self.ctx, self.pins, self.preference,
                               self.never_auto_drivers)
            if soft_pinned:
                why = self._method_requires_problem(comp, b)
                if why is not None:            # the adopted method's OWN requires can't be met here
                    raise ResolveError(why, 'unmet-require')   # (B15 / routing-10): drop the soft pin
            return b
        except ResolveError as e:
            if not soft_pinned:
                raise
            unpinned = {k: v for k, v in self.pins.items() if k != comp.name}
            b = select_binding(comp, self.cascade, self.ctx, unpinned, self.preference,
                               self.never_auto_drivers)
            self.dropped.setdefault(comp.name, str(e))
            return b

    def _method_requires_problem(self, comp, binding):
        '''Why `binding`'s method-specific HARD requirements (its own `requires:` + its driver's) can't
        be met here, or None — tried in a scratch resolution under the HARD pins only, the way
        gated_context tries a driver. Only asked for a soft-pinned (detected) method.'''
        drv = _driver(binding, self.cascade, self.block) if binding.via != 'parts' else None
        reqs = [(c, cap_constraints(binding.details.get('requires')).get(c))
                for c in cap_names(binding.details.get('requires'))]
        reqs += [(c, None) for c in self.drivers.get(binding.via, [])]
        if binding.via == 'native' and drv and drv != binding.via:
            reqs += [(c, None) for c in self.drivers.get(drv, [])]
        if not reqs:
            return None
        hard = {k: v for k, v in self.pins.items() if k not in self.soft}
        st = _State(self.cascade, self.components, self.drivers, self.ctx, hard, self.overrides,
                    self.preference, self.never_auto_drivers, shared=(self.providers, self.never_auto))
        try:
            for cap, con in reqs:
                st._satisfy(cap, con, comp.name, comp.name)
            st.drain()
        except ResolveError as e:
            return f'{comp.name}: the installed method via:{binding.via} needs {e}'
        return None

    def drain(self, errors=None, kinds=None):
        '''Close requirements to a fixpoint. Strict by default (a missing/ambiguous HARD
        provider raises). If `errors` is given, catch such failures into it (keyed by the
        requesting root) and keep going. A SOFT edge (`suggests:`) that can't be satisfied here
        is skipped silently — never an error, in either mode.'''
        while self.queue:
            requiring_key, requiring_name, cap, constraint, root, optional = self.queue.popleft()
            try:
                got = self._satisfy(cap, constraint, root, requiring_name, requiring_key)
                self.units[requiring_key].deps |= got
                if not optional:                 # HARD edges, for pruning a failed unit's dependents
                    self.hard_deps.setdefault(requiring_key, set()).update(got)
            except ResolveError as e:
                if optional:
                    continue                     # a `suggests:` unmet here is simply not pulled
                if errors is None:
                    raise
                if root not in errors:
                    errors[root] = str(e)
                    if kinds is not None:
                        kinds[root] = e.kind
                self.failed_keys.add(requiring_key)   # this unit can't be installed (see _prune_failed)
                self.failure_of.setdefault(requiring_key, str(e))   # why, for every pick it takes down

    def _bindable_viable(self, cap, requiring):
        '''Providers of `cap` that can bind in this context (bootstrap guard: never self-provide).'''
        return [p for p in self.providers.get(cap, []) if p != requiring
                and self._is_bindable(self.components[p])]

    def _is_bindable(self, comp):
        '''Can `comp` provide something here: a binding selects AND its driver packages it (a
        `component-names: { <drv>: { comp: {} } }` drop means "nothing here" — it can't satisfy a
        HARD requirement, exactly like a `{}`-removed component; B15 / routing-07).'''
        try:
            binding = self._select_binding(comp)
        except ResolveError:
            return False
        if binding.via != 'parts' and self.overrides:
            drv = _driver(binding, self.cascade, self.block)
            if _name_override(self.overrides, drv, comp.name)[1]:
                return False
        return True

    def _pick_provider(self, cap, cands, requiring, constraint=None):
        '''The provider to auto-pull among `cands` (already past pins / soft pins / the version
        constraint / reuse): the only one, else the strict highest component `standing:` rank. Equal
        top rank is an ambiguity error naming BOTH fixes — a provider-pin (this machine) or a
        `standing:` rank (the definitions). Records the deciding rule in `provider_rules`.'''
        if len(cands) == 1:
            self.provider_rules[cap] = 'only provider here'
            return cands[0]
        rank = provider_standing(self.components)
        ranked = sorted(cands, key=lambda p: -rank(p))
        top = [p for p in ranked if rank(p) == rank(ranked[0])]
        what = f'{cap} {constraint}' if constraint else cap
        if len(top) > 1:
            tied = sorted(top)
            how = (f'equal standing: {rank(top[0])}' if rank(top[0]) else 'none ranked by standing:')
            raise AmbiguityError(f'ambiguous providers for "{what}": {tied} (required by {requiring}; '
                               f'{how}) — needs a provider-pin (`pins: {{ {cap}: {tied[0]} }}`) or a '
                               f'component `standing: <integer>` rank (higher wins)')
        self.provider_rules[cap] = f'standing: {rank(top[0])}'
        return top[0]

    def _version_scoped(self, cap):
        '''True if `cap` has VERSION-SCOPED providers — provider components that each declare a fixed
        COMPONENT-level version (python3.11/12/13, jdk-17/21). A constraint on such a cap SELECTS a
        provider by version and fails if none carries it. A cap with no component-level version
        (go/ghc — version lives on a binding/method) is NOT scoped: a constraint there is a soft floor.'''
        return any(self.components[p].prov_versions.get(cap) is not None
                   for p in self.providers.get(cap, []))

    def _self_held(self, keys, requiring_key):
        '''True if `keys` (a resident / cached provider set) includes the REQUIRER's own unit — a
        provider never satisfies its own requirement (gcc-16 {provides: cc, requires: cc} must pull a
        DIFFERENT cc provider, not depend on itself).'''
        return requiring_key is not None and requiring_key in (keys or ())

    def _satisfy(self, cap, constraint, root, requiring, requiring_key=None):
        pin = self.pins.get(cap)
        if (pin is not None and cap in self.soft
                and not (pin in self.via_names or pin not in self.components)):
            # a SOFT provider-pin (detected-installed): try it; if it can't satisfy this edge (fails
            # the constraint / isn't viable here), drop it for this edge and select normally.
            try:
                return self._satisfy_pinned(cap, constraint, root, requiring, requiring_key, pin)
            except ResolveError as e:
                got = self._satisfy_pinned(cap, constraint, root, requiring, requiring_key, None)
                self.dropped.setdefault(cap, str(e))
                return got
        return self._satisfy_pinned(cap, constraint, root, requiring, requiring_key, pin)

    def _satisfy_pinned(self, cap, constraint, root, requiring, requiring_key, pin):
        # `pins:` is one flat namespace for BOTH binding-pins (comp -> via) and provider-pins
        # (cap -> provider component). Here we satisfy a CAPABILITY, so only a PROVIDER-pin applies.
        # A pin whose value names a via/driver is a BINDING-pin — even when that name is ALSO a
        # component (pyenv, flatpak, clang, …); classifying it via-first (matching actions.validate_pin
        # and routecheck) is what stops `pins: {python3.13: pyenv}` from being misread as a provider-
        # pin and throwing a bogus "python3.13 pinned to pyenv, which cannot provide it here". The
        # binding-pin is honored later in _matching when the component `cap` itself resolves.
        if pin is not None and (pin in self.via_names or pin not in self.components):
            pin = None
        if constraint:
            return self._satisfy_constrained(cap, constraint, root, requiring, pin, requiring_key)
        # --- unconstrained: the single-resident DEFAULT path (byte-identical to pre-Phase-2) ---
        # Fast reuse path — but a provider-pin is TOP precedence and must never be shadowed by reuse
        # (the inventory hit would otherwise silently ignore a pin on an env-provided or already-
        # wanted capability). With a pin present we fall through and honor it.
        self_held = self._self_held(self.inventory.get(cap), requiring_key)
        if pin is None and cap in self.inventory and not self_held:
            return self.inventory[cap]                  # reuse (keys, or empty for env)
        viable = self._bindable_viable(cap, requiring)
        if not viable:
            raise ResolveError(f'nothing provides "{cap}" here (required by {requiring})', 'unmet-require')
        if pin is not None:                             # provider-pin (may name a never-auto one)
            if pin not in viable:
                raise ResolveError(f'"{cap}" pinned to {pin!r}, which cannot provide it here',
                                   'pin-unrealizable')
            chosen = pin
        else:
            # never-auto providers aren't AUTO-pulled to satisfy a CAPABILITY (e.g. a versioned gcc-13
            # must not silently become the `cc`/`cxx` provider) — a pin or explicit want enables
            # them. BUT requiring a component by its OWN NAME (`requires: gcc-10`, where the provider
            # p == the required cap) IS that explicit want, so it bypasses never-auto.
            auto = [p for p in viable if p not in self.never_auto or p == cap]
            if not auto:
                hint = f' — enable one with a provider-pin, e.g. pins: {{ {cap}: {viable[0]} }}'
                raise ResolveError(f'nothing auto-provides "{cap}" here (required by {requiring}){hint}',
                                   'unmet-require')
            chosen = self._pick_provider(cap, auto, requiring)
        keys = self.add_component(chosen, root)
        if not self_held:                               # the requirer stays the default resident
            self.inventory[cap] = keys
            self.resident_version[cap] = self.components[chosen].prov_versions.get(cap)
        return keys

    def _satisfy_constrained(self, cap, constraint, root, requiring, pin, requiring_key=None):
        '''Version-scoped selection: pick/reuse the resident whose PROVIDED version meets `constraint`
        (`>=12`, `<12`, …). Lets two consumers of one capability run different versions side-by-side,
        and a constraint ENABLES a never-auto provider (like a by-name require does — the constraint IS
        an explicit selection). A provider-pin still wins if it also meets the constraint.'''
        from .versionsweep import meets
        # 1. the default resident, if it meets the constraint
        # (never the requirer itself: a provider doesn't satisfy its own requirement)
        if (pin is None and cap in self.inventory and meets(self.resident_version.get(cap), constraint)
                and not self._self_held(self.inventory[cap], requiring_key)):
            return self.inventory[cap]
        # 2. a prior resident pulled for this exact (cap, constraint)
        ck = (cap, constraint)
        if (pin is None and ck in self.constrained
                and not self._self_held(self.constrained[ck], requiring_key)):
            return self.constrained[ck]
        # 3. pull a provider whose declared version satisfies the constraint
        viable = [p for p in self._bindable_viable(cap, requiring)
                  if meets(self.components[p].prov_versions.get(cap), constraint)]
        if not viable:
            # SOFT toolchain floor: a NON-version-scoped cap (no provider declares a component-level
            # version — go/ghc, whose version lives on a binding/method like the go tarball's
            # `provides: {go: ">=1.21"}`) resolves with its DEFAULT provider; the floor becomes an
            # ADVISORY (flooradvise + the resident-floor check surface it / auto-tighten) instead of a
            # HARD failure. A version-scoped cap (python3.11/12, jdk-17/21) still fails — you asked for
            # a version that no provider carries. A provider-pin also stays hard.
            if pin is None and not self._version_scoped(cap):
                return self._satisfy(cap, None, root, requiring, requiring_key)
            raise ResolveError(f'nothing provides "{cap} {constraint}" here (required by {requiring})',
                               'unmet-require')
        if pin is not None:
            if pin not in viable:
                raise ResolveError(f'"{cap}" pinned to {pin!r}, which cannot provide '
                                   f'"{cap} {constraint}" here', 'pin-unrealizable')
            chosen = pin
        else:                                           # the constraint enables never-auto; prefer ordinary on a tie
            pool = [p for p in viable if p not in self.never_auto] or viable
            if len(pool) == 1:
                chosen = pool[0]
            elif self._version_scoped(cap):
                # Several VERSION-SCOPED providers meet the constraint and the unconstrained default
                # didn't qualify (e.g. `python3 <3.12` with 3.10 AND 3.11 present, default 3.13 out of
                # range). Pick the HIGHEST provided version that satisfies it — the newest Python/JDK
                # meeting the bound is the unsurprising choice, and it's deterministic, so a plain
                # upper/lower bound needs no provider-pin. (A pin still overrides above.)
                from .osversion import parse_version
                chosen = max(pool, key=lambda p: (parse_version(
                    str(self.components[p].prov_versions.get(cap))) or (), p))
            else:
                chosen = self._pick_provider(cap, pool, requiring, constraint)
        keys = self.add_component(chosen, root)
        if not self._self_held(self.constrained.get(ck), requiring_key):
            self.constrained[ck] = keys
        if cap not in self.inventory:                   # nothing unconstrained yet -> this is the default too
            self.inventory[cap] = keys
            self.resident_version[cap] = self.components[chosen].prov_versions.get(cap)
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
