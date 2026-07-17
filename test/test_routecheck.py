'''The static ambiguity checker: set-inclusion specificity over the finite grid, and
"overlapping-but-incomparable = error".'''

import os

import pytest

from configsys import routes
from configsys.routecheck import AmbiguityError, check_all, check_component
from configsys.predicate import comparable, overlap, parse, subset
from configsys.routes import Binding, Component


@pytest.fixture(scope='module')
def cascade():
    c, _components, _m = routes.load(os.path.join(os.path.dirname(__file__), '..', 'routes.hu'))
    return c


def P(expr):
    return parse(expr)


# -- the relations themselves --------------------------------------------

def test_subset_and_comparability(cascade):
    # ubuntu<23.04 is strictly inside ubuntu (any version)
    assert subset(P('ubuntu < 23.04'), P('ubuntu'), cascade)
    assert not subset(P('ubuntu'), P('ubuntu < 23.04'), cascade)
    # pop_os! is inside ubuntu
    assert subset(P('pop_os!'), P('ubuntu'), cascade)
    # scale safety: debian<12 and ubuntu are disjoint (debian's scale never hits Pop/Ubuntu)
    assert not overlap(P('debian < 12'), P('ubuntu'), cascade)


def test_disjoint_families_dont_overlap(cascade):
    assert not overlap(P('fedora'), P('arch'), cascade)
    assert not overlap(P('fedora'), P('debian'), cascade)


def test_cross_axis_is_incomparable_and_overlapping(cascade):
    # the classic: "any x86_64" vs "any debian" overlap at debian-x86_64, neither wins
    a, b = P('cpu: x86_64'), P('debian')
    assert overlap(a, b, cascade)
    assert not comparable(a, b, cascade)


def test_guarded_not_subset(cascade):
    # (ubuntu and not pop_os!) is inside ubuntu, disjoint from pop_os!
    carved = P('ubuntu and not pop_os!')
    assert subset(carved, P('ubuntu'), cascade)
    assert not overlap(carved, P('pop_os!'), cascade)


# -- the component check --------------------------------------------------

def _component(name, *whens):
    return Component(name, {'install': [
        ({'via': 'native'} if w is None else {'via': 'native', 'when': w}) for w in whens]})


def test_real_routes_are_unambiguous(cascade):
    _c, components, _m = routes.load(os.path.join(os.path.dirname(__file__), '..', 'routes.hu'))
    check_all(components, cascade)          # must not raise


def test_broad_default_plus_narrow_override_is_fine(cascade):
    # steam's shape: a narrow binding + an unguarded default — comparable, no error
    check_component('steamish', _component('steamish', 'pop_os!', None), cascade)


def test_overlapping_incomparable_bindings_raise(cascade):
    bad = _component('oops', 'cpu: x86_64', 'debian')     # overlap at debian-x86_64, incomparable
    with pytest.raises(AmbiguityError) as ei:
        check_component('oops', bad, cascade)
    assert 'oops' in str(ei.value) and 'debian' in str(ei.value)


def test_disjoint_bindings_are_fine(cascade):
    check_component('ok', _component('ok', 'fedora', 'arch'), cascade)


def test_component_rejects_unknown_top_level_key():
    # a stray/removed construct (e.g. the old inline `dotfiles:` node) must fail loudly at
    # load time, not vanish silently — config lives in a required `<name>-dotfiles` component.
    from configsys.errors import ConfigError
    with pytest.raises(ConfigError, match=r'unknown key.*dotfiles'):
        Component('foo', {'dotfiles': {'src': 'a', 'dst': 'b'}, 'install': []})
    # the known keys are accepted
    Component('ok', {'provides': 'cap', 'requires': 'x', 'parts': [], 'install': []})


def test_package_pulls_its_dotfiles_component():
    # regression: vulkan-sdk (tarball) must still bring its config, now as a required
    # `-dotfiles` component (guards against the inline-node -> requires refactor dropping it).
    r = routes.Resolver(os.path.join(os.path.dirname(__file__), '..', 'routes.hu'),
                        'pop_os!', '22.04', 'x86_64')
    keys = set(r.resolve_names(['vulkan-sdk']))
    assert 'dotfiles\\vulkan-sdk-dotfiles' in keys
    assert 'tarball\\vulkan-sdk' in keys
