'''Coexistence detection: after inspect, a component's OTHER (non-managed) install methods are
probed and surfaced as `also_present` — package managers enumerated ONCE (batched), no get_latest.'''

import types

from configsys.installState import (ComponentState, detect_coexisting,
                                     plan_with_swaps, superseded_installs)
from configsys.routes import Resolver
from configsys.runner import Result

OS = ('os: { linux: {}  debian: { using: linux  native: apt } }')


def _routes(tmp_path, comps):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  components: { ' + comps + ' } }', encoding='utf-8')
    return str(p)


class StubRunner:
    '''Only flatpak has an install; everything else "not found".'''
    def __init__(self):
        self.calls = []

    def run(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd.startswith('flatpak list'):
            return Result(cmd, 0, stdout='org.x.Browser\t1.0\n')
        return Result(cmd, 1)


def _managed_state(units):
    (key, rc), = units.items()
    return key, ComponentState(component=rc, supported=True, present=False, installed_version=None,
                               latest_version=None, locked=False, lock_source=None, managed=False,
                               error=None)


def test_coexisting_flatpak_surfaced_while_native_is_managed(tmp_path):
    comps = 'browser: { install: [ { via: native } { via: flatpak  app: org.x.Browser } ] }'
    r = Resolver(_routes(tmp_path, comps), 'debian', '12')
    units = r.resolve_resilient(['browser'])[0]
    key, st = _managed_state(units)
    assert st.component.via == 'native'                 # native is the managed method
    runner = StubRunner()
    ctx = types.SimpleNamespace(routes=r, runner=runner, paths=None)

    detect_coexisting(ctx, {key: st})

    assert st.also_present == (('flatpak', 'org.x.Browser', '1.0'),)   # the coexisting flatpak found
    # batched: the flatpak enumerator ran ONCE (not once per lookup), and NO get_latest was called
    assert sum(1 for c in runner.calls if c.startswith('flatpak list')) == 1
    assert not any('remote-info' in c or 'appstream' in c for c in runner.calls)


def test_single_method_component_gets_no_also_present(tmp_path):
    comps = 'solo: { install: [ { via: flatpak  app: org.x.Solo } ] }'
    r = Resolver(_routes(tmp_path, comps), 'debian', '12')
    units = r.resolve_resilient(['solo'])[0]
    key, st = _managed_state(units)
    runner = StubRunner()
    detect_coexisting(types.SimpleNamespace(routes=r, runner=runner, paths=None), {key: st})
    assert st.also_present == ()                         # only one method -> nothing else to find
    assert not runner.calls                              # and no probing done at all


# -- method-switch swap: superseded_installs + plan_with_swaps ------------------

class FlatpakInstalledRunner:
    '''The flatpak build of the app IS installed (so a switch AWAY from flatpak has an old install
    to remove); nothing else is found.'''
    def run(self, cmd, **kw):
        if cmd.startswith('flatpak info'):
            return Result(cmd, 0, stdout='Version: 1.0\n')
        return Result(cmd, 1)


def test_superseded_finds_the_old_method_install(tmp_path):
    # target = native (apt); the SAME component is also installed via flatpak -> that's superseded.
    comps = 'browser: { install: [ { via: native } { via: flatpak  app: org.x.Browser } ] }'
    r = Resolver(_routes(tmp_path, comps), 'debian', '12')
    units = r.resolve_resilient(['browser'])[0]
    (key, target), = units.items()
    assert target.via == 'native'
    ctx = types.SimpleNamespace(routes=r, runner=FlatpakInstalledRunner(), paths=None)

    olds = superseded_installs(ctx, target)
    assert len(olds) == 1
    old_rc, ver = olds[0]
    assert old_rc.via == 'flatpak' and ver == '1.0'      # the coexisting flatpak, to be removed


def test_plan_with_swaps_injects_remove_of_old_method(tmp_path):
    comps = 'browser: { install: [ { via: native } { via: flatpak  app: org.x.Browser } ] }'
    r = Resolver(_routes(tmp_path, comps), 'debian', '12')
    units = r.resolve_resilient(['browser'])[0]
    (key, target), = units.items()
    ctx = types.SimpleNamespace(routes=r, runner=FlatpakInstalledRunner(), paths=None)

    plan, units2 = plan_with_swaps(ctx, [('install', key, target)], dict(units))
    ops = {(op, k) for op, k, _rc in plan}
    old_key = 'flatpak\\browser'
    assert ('install', key) in ops                       # the new method still installs
    assert ('remove', old_key) in ops                    # the old method is queued for removal
    assert old_key in units2                             # and its unit is available for ordering


def test_plan_with_swaps_noop_when_no_other_method_installed(tmp_path):
    # nothing installed via the other method (runner finds nothing) -> plan is unchanged.
    comps = 'browser: { install: [ { via: native } { via: flatpak  app: org.x.Browser } ] }'
    r = Resolver(_routes(tmp_path, comps), 'debian', '12')
    units = r.resolve_resilient(['browser'])[0]
    (key, target), = units.items()
    ctx = types.SimpleNamespace(routes=r, runner=StubRunner(), paths=None)  # apt+flatpak both absent

    plan, units2 = plan_with_swaps(ctx, [('install', key, target)], dict(units))
    assert plan == [('install', key, target)]            # no swap added
    assert set(units2) == set(units)
