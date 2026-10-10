'''Regressions for resolver fixes (docs-audit batch B): component-level `parts:` (#4), a provider
never satisfying its own requirement (#5), pin precedence user > auto-tighten > detected (#7),
detected soft pins staying SOFT under a version constraint (#8), and component-level integer
`standing:` ranking providers (#12).'''

import os

import pytest

from configsys import resolve
from configsys.resolve import ResolveError
from configsys.routes import Resolver, load

HERE = os.path.dirname(__file__)
ROUTES = os.path.join(HERE, '..', 'routes.hu')
OS = 'os: { linux: {}  debian: { using: linux  native: apt } }'


def _routes(tmp_path, comps):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  components: { ' + comps + ' } }')
    return str(p)


# -- #4 component-level parts: ----------------------------------------------------------------

def test_component_level_parts_resolves_to_its_parts(tmp_path):
    r = Resolver(_routes(tmp_path, '''
        btop:      { install: [ { via: native } ] }
        ripgrep:   { install: [ { via: native } ] }
        my-bundle: { parts: [ btop ripgrep ] }'''), 'debian', '12')
    assert set(r.resolve_names(['my-bundle'])) == {'apt\\btop', 'apt\\ripgrep'}


def test_component_level_parts_in_a_user_layer(tmp_path):
    routes = _routes(tmp_path, '''
        btop:    { install: [ { via: native } ] }
        ripgrep: { install: [ { via: native } ] }''')
    user = tmp_path / 'user.hu'
    user.write_text('{ components: { my-bundle: { parts: [ btop ripgrep ] } } }')
    r = Resolver(routes, 'debian', '12', overrides_path=str(user))
    assert set(r.resolve_names(['my-bundle'])) == {'apt\\btop', 'apt\\ripgrep'}


def test_component_level_parts_beside_install_is_inert_and_check_warns(tmp_path):
    from configsys import routecheck
    casc, comps, drivers, _co = load(_routes(tmp_path, '''
        btop:  { install: [ { via: native } ] }
        mixed: { parts: [ btop ]  install: [ { via: native } ] }'''))
    assert [b.via for b in comps['mixed'].bindings] == ['native']   # install: wins, parts inert
    issues = routecheck.validate(comps, casc, drivers)
    assert any(i.kind == 'parts-ignored' and i.component == 'mixed' for i in issues)


# -- #5 a provider never satisfies its own requirement ---------------------------------------

def test_provider_does_not_satisfy_its_own_requirement(tmp_path):
    r = Resolver(_routes(tmp_path, '''
        gcc-16:      { provides: cc  requires: cc  install: [ { via: native } ] }
        c-toolchain: { provides: cc  install: [ { via: native } ] }'''), 'debian', '12')
    u = r.resolve_names(['gcc-16'])
    assert 'apt\\c-toolchain' in u                         # pulled a DIFFERENT cc provider
    assert 'apt\\gcc-16' not in u['apt\\gcc-16'].deps        # no self-dependency
    assert 'apt\\c-toolchain' in u['apt\\gcc-16'].deps


def test_self_provider_with_no_other_provider_is_an_honest_error(tmp_path):
    r = Resolver(_routes(tmp_path, '''
        gcc-16: { provides: cc  requires: cc  install: [ { via: native } ] }'''), 'debian', '12')
    with pytest.raises(ResolveError, match='nothing provides "cc"'):
        r.resolve_names(['gcc-16'])


def test_self_held_requirement_keeps_the_explicit_want_as_resident(tmp_path):
    # another consumer of cc still reuses the explicitly wanted gcc-16 (it stays the resident)
    r = Resolver(_routes(tmp_path, '''
        gcc-16:      { provides: cc  requires: cc  install: [ { via: native } ] }
        c-toolchain: { provides: cc  install: [ { via: native } ] }
        app:         { requires: cc  install: [ { via: native } ] }'''), 'debian', '12')
    u = r.resolve_names(['gcc-16', 'app'])
    assert u['apt\\app'].deps == {'apt\\gcc-16'}


# -- #7 user pin > auto-tighten > detected --------------------------------------------------

def test_user_pin_beats_auto_tighten_pin(tmp_path):
    r = Resolver(_routes(tmp_path, '''
        tool: { install: [ { via: native }  { via: tarball  installDir: "x/tool" } ] }'''),
        'debian', '12', pins={'tool': 'native'})
    units, errs = r.resolve_resilient(['tool'], extra_pins={'tool': 'tarball'})
    assert not errs and set(units) == {'apt\\tool'}           # YOUR pin wins
    # with no user pin, the tighten pin applies; and it outranks a detected soft pin
    r2 = Resolver(str(tmp_path / 'routes.hu'), 'debian', '12')
    units, _ = r2.resolve_resilient(['tool'], extra_pins={'tool': 'tarball'},
                                    soft_pins={'tool': 'native'})
    assert set(units) == {'tarball\\tool'}


def test_flooradvise_names_a_user_pin_that_fails_a_floor(monkeypatch):
    from configsys import flooradvise
    from types import SimpleNamespace as NS

    meth = lambda via, latest, default, pinned=False: NS(via=via, latest=latest, is_default=default,
                                                         is_pinned=pinned, installed=False)
    rp = NS(methods=[meth('native', '1.2', True, True), meth('tarball', '1.9', False)])
    comps = {'app': NS(name='app', requires=['rust'], req_versions={'rust': '>=1.5'}, bindings=[],
                       prov_versions={}),
             'rust': NS(name='rust', requires=[], req_versions={}, bindings=[], prov_versions={},
                        provides=['rust'])}
    ctx = NS(routes=NS(components=comps),
             config=NS(pins=lambda: {'rust': 'native'}, auto_tighten=lambda: True))
    monkeypatch.setattr(flooradvise, 'providers_of', lambda _c, cap: ['rust'])
    import configsys.versionreport as vr
    monkeypatch.setattr(vr, 'report', lambda _ctx, name: rp)
    unit = NS(comp='app', via='native')
    advs = flooradvise.advise(ctx, [unit])
    assert len(advs) == 1 and advs[0]['tag'] == 'pin-floor'
    t = advs[0]['text']
    assert 'pinned to native' in t and '1.2' in t and '>=1.5' in t and 'tarball' in t
    assert 'auto-tighten' in t                                  # names what auto-tighten would pick
    assert flooradvise.tighten_pins(ctx, [unit]) == {}          # never overrides YOUR pin


# -- #8 detected soft pins are SOFT -----------------------------------------------------------

def test_detected_pin_failing_a_version_constraint_is_dropped_not_an_error(tmp_path):
    user = tmp_path / 'user.hu'
    user.write_text('{ components: { t-ge313: { requires: [ { python3: ">=3.13" } ]  '
                    'install: [ { via: native } ] } } }')
    r = Resolver(ROUTES, 'ubuntu', '24.04', overrides_path=str(user))
    units, errs = r.resolve_resilient(['t-ge313'], soft_pins={'python3': 'python3.12'})
    assert errs == {}
    comps = {rc.comp for rc in units.values()}
    assert 'python3.13' in comps and 'python3.12' not in comps
    assert 'python3' in r.dropped_soft_pins                    # recorded for `where`/diagnostics


def test_same_pin_as_a_user_pin_stays_hard(tmp_path):
    user = tmp_path / 'user.hu'
    user.write_text('{ components: { t-ge313: { requires: [ { python3: ">=3.13" } ]  '
                    'install: [ { via: native } ] } } }')
    r = Resolver(ROUTES, 'ubuntu', '24.04', overrides_path=str(user),
                 pins={'python3': 'python3.12'})
    _units, errs = r.resolve_resilient(['t-ge313'])
    assert 'pinned to' in errs.get('t-ge313', '')              # YOUR pin is a filter, not a hint


def test_soft_binding_pin_naming_an_invalid_method_falls_through(tmp_path):
    r = Resolver(_routes(tmp_path, '''
        tool: { install: [ { via: native } ] }'''), 'debian', '12')
    units, errs = r.resolve_resilient(['tool'], soft_pins={'tool': 'flatpak'})
    assert errs == {} and set(units) == {'apt\\tool'}
    assert 'tool' in r.dropped_soft_pins


def test_honorable_soft_pin_is_still_adopted(tmp_path):
    r = Resolver(_routes(tmp_path, '''
        app: { requires: cap  install: [ { via: native } ] }
        a:   { provides: cap  install: [ { via: native } ] }
        b:   { provides: cap  standing: never-auto  install: [ { via: native } ] }'''), 'debian', '12')
    units, errs = r.resolve_resilient(['app'], soft_pins={'cap': 'b'})
    assert errs == {} and 'apt\\b' in units and 'apt\\a' not in units
    assert r.dropped_soft_pins == {}


# -- #12 component-level integer standing ranks providers ------------------------------------

def test_component_standing_rank_picks_a_provider_without_a_pin(tmp_path):
    r = Resolver(_routes(tmp_path, '''
        app: { requires: cap  install: [ { via: native } ] }
        a:   { provides: cap  standing: 5  install: [ { via: native } ] }
        b:   { provides: cap  install: [ { via: native } ] }'''), 'debian', '12')
    units, errs = r.resolve_resilient(['app'])
    assert errs == {} and 'apt\\a' in units and 'apt\\b' not in units
    assert r.provider_rules.get('cap') == 'standing: 5'


def test_equal_component_standing_stays_an_ambiguity_naming_standing(tmp_path):
    r = Resolver(_routes(tmp_path, '''
        app: { requires: cap  install: [ { via: native } ] }
        a:   { provides: cap  standing: 3  install: [ { via: native } ] }
        b:   { provides: cap  standing: 3  install: [ { via: native } ] }'''), 'debian', '12')
    with pytest.raises(ResolveError) as e:
        r.resolve_names(['app'])
    msg = str(e.value)
    assert 'ambiguous providers' in msg and 'standing' in msg and 'provider-pin' in msg


def test_unranked_providers_remain_ambiguous(tmp_path):
    r = Resolver(_routes(tmp_path, '''
        app: { requires: cap  install: [ { via: native } ] }
        a:   { provides: cap  install: [ { via: native } ] }
        b:   { provides: cap  install: [ { via: native } ] }'''), 'debian', '12')
    with pytest.raises(ResolveError, match='ambiguous providers'):
        r.resolve_names(['app'])


def test_pin_beats_component_standing(tmp_path):
    r = Resolver(_routes(tmp_path, '''
        app: { requires: cap  install: [ { via: native } ] }
        a:   { provides: cap  standing: 5  install: [ { via: native } ] }
        b:   { provides: cap  install: [ { via: native } ] }'''), 'debian', '12', pins={'cap': 'b'})
    assert 'apt\\b' in r.resolve_names(['app'])


def test_never_auto_still_excluded_from_standing_ranking(tmp_path):
    r = Resolver(_routes(tmp_path, '''
        app: { requires: cap  install: [ { via: native } ] }
        a:   { provides: cap  install: [ { via: native } ] }
        b:   { provides: cap  standing: never-auto  install: [ { via: native } ] }'''), 'debian', '12')
    assert 'apt\\a' in r.resolve_names(['app'])
    assert resolve.provider_standing(r.components)('b') == 0
