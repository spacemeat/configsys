'''planning.py — order and expand an execution plan by dependencies.

Units carry `deps` (keys of units that must be installed first). Given a staged
plan, we:
  * expand install/upgrade ops to also install a unit's transitive deps (skipping
    any the live state says are already present), so prerequisites like apt\\flatpak
    come along automatically and show up in the confirm summary;
  * order the whole plan: installs/upgrades dependency-first, then locks/unlocks,
    then removes in reverse dependency order (so you never remove a dep out from
    under something still present).
'''

_INSTALLISH = ('install', 'upgrade', 'set-version')


def dependency_order(units):
    '''Unit keys in dependency-first (topological) order. Cycles are broken.'''
    order, done, active = [], set(), set()

    def visit(key):
        if key in done or key in active:
            return
        active.add(key)
        rc = units.get(key)
        if rc is not None:
            for dep in sorted(rc.deps):
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
    removes = sorted((k for k, op in ops.items() if op == 'remove'),
                     key=lambda k: -idx.get(k, 0))

    ordered_keys = installs + locks + removes
    return [(ops[k], k, units.get(k)) for k in ordered_keys]
