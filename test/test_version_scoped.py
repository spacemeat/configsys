'''Version-scoped providers (Phase 2): a versioned `provides: {cap: N}` + a constrained
`requires: {cap: ">=N"}` select a resident by version, and two consumers wanting different versions
of one capability coexist. The unconstrained path is unchanged (covered elsewhere / the golden).'''

import pytest

from configsys.routes import Resolver
from configsys.resolve import ResolveError

OS = 'os: { linux: {}  debian: { using: linux  native: apt } }'


def _resolve(tmp_path, comps, names, pins=None):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  components: { ' + comps + ' } }')
    return set(Resolver(str(p), 'debian', '12', pins=pins).resolve_names(names))


# tk-11 is opt-in (not the default); tk-12 is the default. Both provide the `tk` capability, versioned.
TK = '''
    tk-11: { provides: { tk: 11 }  opt-in: true  install: [ { via: native } ] }
    tk-12: { provides: { tk: 12 }              install: [ { via: native } ] }
    generic:  { requires: tk                    install: [ { via: native } ] }
    want-12:  { requires: { tk: ">=12" }        install: [ { via: native } ] }
    want-11:  { requires: { tk: "<12" }         install: [ { via: native } ] }
'''


def test_unconstrained_takes_the_default_provider(tmp_path):
    got = _resolve(tmp_path, TK, ['generic'])
    assert 'apt\\tk-12' in got and 'apt\\tk-11' not in got        # -11 opt-in -> -12 default


def test_constraint_selects_the_matching_version(tmp_path):
    assert 'apt\\tk-12' in _resolve(tmp_path, TK, ['want-12'])    # >=12 -> tk-12
    # <12 ENABLES the opt-in tk-11 (a constraint is an explicit selection) and excludes tk-12
    got = _resolve(tmp_path, TK, ['want-11'])
    assert 'apt\\tk-11' in got and 'apt\\tk-12' not in got


def test_two_versions_coexist_per_consumer(tmp_path):
    # generic -> tk-12 (default); want-11 (<12) -> tk-11; both residents present at once
    got = _resolve(tmp_path, TK, ['generic', 'want-11'])
    assert 'apt\\tk-11' in got and 'apt\\tk-12' in got


def test_constraint_met_by_default_reuses_it(tmp_path):
    # generic pulls tk-12 first; want-12's >=12 is met by the default resident -> no second unit
    got = _resolve(tmp_path, TK, ['generic', 'want-12'])
    assert 'apt\\tk-12' in got and 'apt\\tk-11' not in got


def test_unsatisfiable_constraint_errors(tmp_path):
    comps = TK + '  want-99: { requires: { tk: ">=99" }  install: [ { via: native } ] }'
    with pytest.raises(ResolveError) as e:
        _resolve(tmp_path, comps, ['want-99'])
    assert 'tk >=99' in str(e.value)


def test_provider_pin_still_wins_when_it_meets_the_constraint(tmp_path):
    # pin tk -> tk-12; a >=12 consumer is fine (pin meets it)
    assert 'apt\\tk-12' in _resolve(tmp_path, TK, ['want-12'], pins={'tk': 'tk-12'})
    # but a pin that violates the constraint errors clearly
    with pytest.raises(ResolveError) as e:
        _resolve(tmp_path, TK, ['want-11'], pins={'tk': 'tk-12'})
    assert 'cannot provide' in str(e.value)
