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
    tk-11: { provides: { tk: 11 }  standing: never-auto  install: [ { via: native } ] }
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


# The opencv + blender shape: blender needs the `cuda-toolkit` CAPABILITY (steerable by a provider-pin),
# opencv-cuda12 needs the `cuda-toolkit-12` COMPONENT by name (insulated from that pin) — so a global
# cuda pin steers blender WITHOUT dragging opencv off its required version, and both coexist.
BY_NAME = TK + '  by-name-12: { requires: tk-12  install: [ { via: native } ] }'


def test_by_name_require_is_insulated_from_a_capability_pin(tmp_path):
    # `generic` uses the tk capability (blender), `by-name-12` names the tk-12 component (opencv).
    # Pinning the tk capability to tk-11 steers generic to 11 but leaves by-name-12 on 12 -> coexist.
    got = _resolve(tmp_path, BY_NAME, ['generic', 'by-name-12'], pins={'tk': 'tk-11'})
    assert 'apt\\tk-11' in got and 'apt\\tk-12' in got            # different versions, both resident


def test_resolution_is_order_independent(tmp_path):
    # a worklist-to-fixpoint has no order dependence: install/resolve order of the two consumers
    # yields the identical unit set (so "install opencv then blender" == "blender then opencv").
    a = _resolve(tmp_path, BY_NAME, ['generic', 'by-name-12'], pins={'tk': 'tk-11'})
    b = _resolve(tmp_path, BY_NAME, ['by-name-12', 'generic'], pins={'tk': 'tk-11'})
    assert a == b and {'apt\\tk-11', 'apt\\tk-12'} <= a


# -- soft toolchain floors: a NON-version-scoped cap resolves + advises, never hard-fails ----------

# `go` provides the cap `go` by name; only its TARBALL binding declares a version (a floor). So the
# cap has NO component-level version -> a constraint on it is a SOFT floor, not a hard selection.
GOFLOOR = '''
    go:       { install: [ { via: native }
                           { via: tarball  provides: { go: ">=1.21" } } ] }
    needsnew: { requires: [ { go: ">=1.21" } ]  install: [ { via: native } ] }
'''


def test_soft_floor_resolves_with_default_when_unmet(tmp_path):
    # the default go (native, unversioned) can't be shown to meet >=1.21, but a non-version-scoped
    # cap resolves with it anyway (the floor is advisory) instead of raising.
    got = _resolve(tmp_path, GOFLOOR, ['needsnew'])
    assert 'apt\\needsnew' in got and 'apt\\go' in got      # resolves + pulls the default go


# the haskell/hlint shape: the floor-meeting method is not just non-default but `never-auto` (ghcup),
# and it carries its own `requires`. The floor must stay SOFT — the default (distro ghc) resolves and
# the never-auto method is NOT force-pulled to satisfy it (an advisory suggests pinning to it).
HASKFLOOR = '''
    curl: { install: [ { via: native } ] }
    hask: { install: [ { via: native }
                       { via: script  standing: never-auto  requires: curl  provides: { hask: ">=9.4" } } ] }
    lint: { requires: [ { hask: ">=9.4" } ]  install: [ { via: native } ] }
'''


def test_never_auto_floor_meeter_stays_soft(tmp_path):
    got = _resolve(tmp_path, HASKFLOOR, ['lint'])
    assert 'apt\\lint' in got and 'apt\\hask' in got          # default (distro) ghc resolves
    assert not any(k.startswith('script\\') for k in got)     # never-auto ghcup NOT auto-pulled


def test_never_auto_floor_meeter_is_pinnable(tmp_path):
    # pinning hask -> its script (ghcup) binding selects the floor-meeting method explicitly
    got = _resolve(tmp_path, HASKFLOOR, ['lint'], pins={'hask': 'script'})
    assert 'script\\hask' in got and 'apt\\lint' in got


def test_version_scoped_floor_with_no_matching_version_still_hard_fails(tmp_path):
    # a VERSION-SCOPED cap (tk-11/12 declare component-level versions) with a floor no provider
    # carries stays a HARD error — you asked for a version that doesn't exist.
    hard = TK + '\n    want-13: { requires: { tk: ">=13" }  install: [ { via: native } ] }'
    with pytest.raises(ResolveError):
        _resolve(tmp_path, hard, ['want-13'])
