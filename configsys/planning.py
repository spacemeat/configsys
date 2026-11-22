'''planning.py — order and expand an execution plan by dependencies.

Units carry `deps` (keys of units they pull in) and `soft_deps` (the subset pulled in only by
`suggests:` — a companion such as `<name>-glue`, which installs AFTER the unit that suggests it: a
soft edge is folded in like any dep but orders the other way, so a companion that hard-requires its
parent — docker-compose-standalone links the plugin docker-compose installs — never runs first).
Given a staged plan, we:
  * expand install/upgrade/set-version ops to also install a unit's transitive deps (skipping
    any the live state says are already present), so prerequisites like apt\\flatpak
    come along automatically and show up in the confirm summary;
  * order the whole plan: swap-removes first (the old method of a component this plan
    reinstalls another way, so it can't clobber the fresh install), then installs/upgrades/
    set-versions dependency-first, then locks/unlocks, then the other removes in reverse
    dependency order (so you never remove a dep out from under something still present).
'''

_INSTALLISH = ('install', 'upgrade', 'set-version')


def dependency_order(units):
    '''Unit keys in dependency-first (topological) order: a unit after its hard deps, and after
    every unit that suggests it. Cycles are broken.'''
    order, done, active = [], set(), set()
    before = {key: set() for key in units}
    for key, rc in units.items():
        soft = getattr(rc, 'soft_deps', set())
        before[key] |= set(rc.deps) - soft
        for dep in soft:
            if dep in before:
                before[dep].add(key)                 # the suggester comes first

    def visit(key):
        if key in done or key in active:
            return
        active.add(key)
        for dep in sorted(before.get(key, ())):
            if dep in units:
                visit(dep)
        active.discard(key)
        done.add(key)
        order.append(key)

    for key in sorted(units):
        visit(key)
    return order


def expand_plan(plan, units, states=None):
    '''plan: iterable of (op, key, rc). Returns an ordered [(op, key, rc)] with
    transitive install deps folded in. `states` (optional {key: ComponentState})
    lets us skip deps that are already present.'''
    order = dependency_order(units)
    idx = {k: i for i, k in enumerate(order)}

    def present(key):
        return bool(states and key in states and states[key].present)

    ops = {}
    for op, key, _rc in plan:
        ops[key] = op

    # Fold in transitive deps of anything being installed/upgraded.
    stack = [k for k, op in ops.items() if op in _INSTALLISH]
    seen = set(stack)
    while stack:
        rc = units.get(stack.pop())
        if rc is None:
            continue
        for dep in rc.deps:
            if dep in ops or present(dep) or dep in seen:
                continue
            seen.add(dep)
            ops[dep] = 'install'
            stack.append(dep)

    installs = sorted((k for k, op in ops.items() if op in _INSTALLISH),
                      key=lambda k: idx.get(k, 0))
    locks = [k for k, op in ops.items() if op in ('lock', 'unlock')]

    # A swap-remove: a `remove` whose COMPONENT also has an install/upgrade in this plan (a
    # different unit/method) — the OLD method being superseded by a method switch. It must run
    # BEFORE the paired install (the two methods may share a binary path, so removing after would
    # clobber the fresh install), overriding the "removes last" rule for that unit.
    install_comps = {units[k].comp for k in installs if units.get(k) is not None}
    all_removes = [k for k, op in ops.items() if op == 'remove']
    swaps = sorted((k for k in all_removes
                    if units.get(k) is not None and units[k].comp in install_comps),
                   key=lambda k: -idx.get(k, 0))
    swap_set = set(swaps)
    removes = sorted((k for k in all_removes if k not in swap_set),
                     key=lambda k: -idx.get(k, 0))

    ordered_keys = swaps + installs + locks + removes
    return [(ops[k], k, units.get(k)) for k in ordered_keys]
