'''Unit tests for the version-floor sweep core (configsys/versionsweep.py).

The core is pure — version lookups are injected — so these run without a network.
'''

from configsys import versionsweep as vs
from configsys.routes import Component


# -- meets() ------------------------------------------------------------------

def test_meets_floor_and_range():
    assert vs.meets('1.97', '>=1.96') is True
    assert vs.meets('1.75', '>=1.96') is False
    assert vs.meets('v1.4.7', '>=1.4') is True             # leading-v normalized
    assert vs.meets('1.96', '1.96') is True                # bare version == exact
    assert vs.meets('2.5', '>=2.0,<3.0') is True           # AND range
    assert vs.meets('3.1', '>=2.0,<3.0') is False


def test_meets_abstains_false_on_unparseable():
    assert vs.meets(None, '>=1.0') is False
    assert vs.meets('nightly', '>=1.0') is False           # unverifiable -> treated as NOT met


# -- collectors ---------------------------------------------------------------

def _comps():
    return {
        'ripgrep-src': Component('ripgrep-src', {
            'requires': [{'cargo': '>=1.96'}, 'cc'],       # a versioned + a bare require
            'install': [{'via': 'source'}]}),
        'rust': Component('rust', {
            'provides': 'cargo',
            'install': [{'via': 'native'},
                        {'via': 'tarball', 'provides': {'cargo': '1.97'}}]}),  # a provides floor
    }


def test_collect_requirement_floors_only_versioned():
    floors = vs.collect_requirement_floors(_comps())
    assert (('ripgrep-src', 'component', 'cargo', '>=1.96')) in [tuple(f) for f in floors]
    # the bare `cc` require carries no version, so it's not a floor
    assert all(cap != 'cc' for _, _, cap, _ in floors)


def test_collect_provides_floors_from_binding():
    floors = vs.collect_provides_floors(_comps())
    assert ('rust', 'via tarball', 'cargo', '1.97') in [tuple(f) for f in floors]


def test_providers_of_includes_self_name_and_provides():
    comps = _comps()
    assert set(vs.providers_of(comps, 'cargo')) == {'rust'}          # provides: cargo
    assert vs.providers_of(comps, 'ripgrep-src') == ['ripgrep-src']  # a component provides its own name


# -- sweep (pure, injected version lookups) -----------------------------------

def test_sweep_flags_stranded_requirement():
    comps = _comps()
    # cargo's best available here is 1.75 (< the 1.96 floor) -> ripgrep-src is stranded
    findings = vs.sweep(comps, {}, best_version=lambda cap: '1.75', method_version=lambda n, w: None)
    stranded = [f for f in findings if f['kind'] == 'stranded']
    assert len(stranded) == 1
    assert stranded[0]['component'] == 'ripgrep-src' and stranded[0]['best'] == '1.75'


def test_sweep_ok_when_floor_met():
    comps = _comps()
    findings = vs.sweep(comps, {}, best_version=lambda cap: '1.97',
                        method_version=lambda n, w: '1.97')
    assert findings == []                                  # floor met AND provides claim honest


def test_sweep_flags_dishonest_provides():
    comps = _comps()
    # requirement is fine (1.97 >= 1.96), but tarball actually delivers 1.50 < its claimed 1.97
    def methv(name, where):
        return '1.50' if where == 'via tarball' else None
    findings = vs.sweep(comps, {}, best_version=lambda cap: '1.97', method_version=methv)
    dishonest = [f for f in findings if f['kind'] == 'dishonest']
    assert len(dishonest) == 1
    assert dishonest[0]['component'] == 'rust' and dishonest[0]['real'] == '1.50'


def test_sweep_provides_abstains_when_version_unknown():
    comps = _comps()
    # method_version returns None (can't verify) -> no dishonest finding (abstain, don't accuse)
    findings = vs.sweep(comps, {}, best_version=lambda cap: '1.97', method_version=lambda n, w: None)
    assert not any(f['kind'] == 'dishonest' for f in findings)
