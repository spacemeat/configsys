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
    units, errs = r.resolve_resilient(['t-ge313'], soft_pins={'python3': 'python3.12'}, record=True)
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
    units, errs = r.resolve_resilient(['tool'], soft_pins={'tool': 'flatpak'}, record=True)
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
    units, errs = r.resolve_resilient(['app'], record=True)
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


# -- review-2026-11-2 routing-23 / -25 / -36 / -37 ------------------------------------------------

_UBU = 'os: { linux: {}  debian: { using: linux  native: apt }  ubuntu: { using: debian } }'


def _ubuntu_routes(tmp_path, comps):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + _UBU + '  components: { ' + comps + ' } }')
    return str(p)


def test_a_broader_binding_never_beats_two_narrower_ones_by_preference(tmp_path):
    # routing-23: native (bare) ⊃ flatpak (ubuntu) and ⊃ tarball (cpu:x86_64), the two narrow ones
    # incomparable — preference decides between THEM; native used to win, and dropping the tarball
    # flipped the default to flatpak
    three = '''x: { install: [ { via: native }  { via: flatpak  app: org.x.X  when: "ubuntu" }
                               { via: tarball  installDir: x  when: "cpu:x86_64" } ] }'''
    r = Resolver(_ubuntu_routes(tmp_path, three), 'ubuntu', None, 'x86_64')
    sel = r.select('x')
    assert sel.binding.via == 'flatpak' and sel.rule == 'driver-preference'
    two = '''x: { install: [ { via: native }  { via: flatpak  app: org.x.X  when: "ubuntu" } ] }'''
    assert Resolver(_ubuntu_routes(tmp_path, two), 'ubuntu', None, 'x86_64').select('x').binding.via == 'flatpak'


def test_a_non_map_component_is_an_error_not_a_tombstone(tmp_path):
    # routing-25: `foo: bar` silently cleared every lower layer's foo
    from configsys.errors import ConfigError
    routes = _routes(tmp_path, 'foo: { install: [ { via: native } ] }')
    user = tmp_path / 'user.hu'
    user.write_text('{ components: { foo: bar } }')
    with pytest.raises(ConfigError, match='foo'):
        load(routes, str(user))
    plug = tmp_path / 'plug' / 'p.hu'
    plug.parent.mkdir()
    plug.write_text('{ components: { foo: bar } }')
    warns = []
    _c, comps, _d, _n = load(routes, None, [(str(plug), 'plugin')], warnings_out=warns)
    assert [b.via for b in comps['foo'].bindings] == ['native']        # the repo's foo stands
    assert any('foo' in w and 'not a scalar' in w for w in warns)
    user.write_text('{ components: { foo: {} } }')                     # `{}` still removes it
    assert load(routes, str(user))[1]['foo'].bindings == []


def test_select_runs_once_per_component_per_resolution(tmp_path, monkeypatch):
    # routing-36: _is_bindable selected each provider, then add_component selected it again
    r = Resolver(_routes(tmp_path, '''
        app: { requires: tool  install: [ { via: native } ] }
        a:   { provides: tool  standing: 2  install: [ { via: native } ] }
        b:   { provides: tool  install: [ { via: native } ] }'''), 'debian', '12')
    calls = []
    real = resolve.select_binding
    monkeypatch.setattr(resolve, 'select_binding', lambda comp, *a, **k: calls.append(comp.name) or real(comp, *a, **k))
    assert set(r.resolve_names(['app'])) == {'apt\\app', 'apt\\a'}
    assert sorted(calls) == ['a', 'app', 'b']


def test_the_gated_context_cache_never_answers_for_a_reused_id(tmp_path):
    # routing-37: keyed on id(components) without holding it — a new dict reusing the id hit the entry
    casc, comps, drivers, _n = load(_routes(tmp_path, 'x: { install: [ { via: native } ] }'))
    first = resolve.gated_context(casc, dict(comps), drivers, 'debian', '12')
    key_obj = dict(comps)
    second = resolve.gated_context(casc, key_obj, drivers, 'debian', '12')
    assert second is not first                                         # a different set: computed anew
    assert resolve.gated_context(casc, key_obj, drivers, 'debian', '12') is second   # the same: cached
    for entry in casc._gated_ctx_cache.values():
        assert entry[1] is drivers                                     # the entry holds what it is keyed on


def test_clear_facet_cache_empties_it():
    from configsys import routes
    routes.detect_facets({'gpu': {'kind': 'categorical', 'detect': 'true', 'match': {'x': 'x'}}},
                         env={'CONFIGSYS_FACET_gpu': 'x'})
    assert routes._FACET_CACHE
    routes.clear_facet_cache()
    assert routes._FACET_CACHE == {}


# -- routing-28: every ResolveError says what kind it is --------------------------------------------

_KIND_CASES = {
    'unknown': ('', {}, ['nosuch']),
    'no-candidate': ('x: { install: [ { via: native  when: "ubuntu" } ] }', {}, ['x']),
    'gated': ('x: { install: [ { via: flatpak  app: org.x.X } ] }', {'disabled': ('flatpak',)}, ['x']),
    'pin-unrealizable': ('x: { install: [ { via: native } ] }', {'pins': {'x': 'flatpak'}}, ['x']),
    'method-tie': ('x: { install: [ { via: cargo  name: x }  { via: pipx  name: x } ] }', {}, ['x']),
    'ambiguous-providers': ('''app: { requires: tool  install: [ { via: native } ] }
        a: { provides: tool  install: [ { via: native } ] }
        b: { provides: tool  install: [ { via: native } ] }''', {}, ['app']),
    'unmet-require': ('app: { requires: "pinned to x"  install: [ { via: native } ] }', {}, ['app']),
}


@pytest.mark.parametrize('kind', sorted(_KIND_CASES))
def test_each_resolve_error_carries_its_kind(kind, tmp_path):
    comps, kw, names = _KIND_CASES[kind]
    r = Resolver(_routes(tmp_path, comps), 'debian', '12', **kw)
    out = {}
    _u, errors = r.resolve_resilient(names, out=out)
    assert set(errors) == set(names) and out['error_kinds'] == {names[0]: kind}
    assert kind in resolve.KINDS
    with pytest.raises(ResolveError) as e:
        r.resolve_names(names)
    assert e.value.kind == kind


def test_check_classifies_resolve_errors_by_kind_not_text(tmp_path, monkeypatch, capsys):
    # a method tie on a pick is the config's to fix (an error row); an unmet require whose message
    # happens to read "pinned to" is not a config error
    from configsys.app import main
    home = tmp_path / 'home'
    base = ['--home', str(home), '--os', 'pop', '-q']
    assert main(base + ['inspect']) in (0, 1)
    cfg = home / '.config' / 'configsys' / 'configsys.hu'
    cfg.write_text('''{
        picks: { this-machine: [ tie  odd ] }
        components: {
            tie: { install: [ { via: cargo  name: tie }  { via: pipx  name: tie } ] }
            odd: { requires: "pinned to y"  install: [ { via: native } ] }
        }
    }''')
    capsys.readouterr()
    main(base + ['check'])
    out = capsys.readouterr().out
    assert "tie: tie: install methods ['cargo', 'pipx'] are equally valid" in out   # the resolve-time row
    assert 'odd: nothing provides' not in out
