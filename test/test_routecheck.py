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
    c, _components, _m, _co = routes.load(os.path.join(os.path.dirname(__file__), '..', 'routes.hu'))
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
    _c, components, _m, _co = routes.load(os.path.join(os.path.dirname(__file__), '..', 'routes.hu'))
    check_all(components, cascade)          # must not raise


def test_broad_default_plus_narrow_override_is_fine(cascade):
    # steam's shape: a narrow binding + an unguarded default — comparable, no error
    check_component('steamish', _component('steamish', 'pop_os!', None), cascade)


def test_overlapping_incomparable_bindings_raise(cascade):
    bad = _component('oops', 'cpu: x86_64', 'debian')     # overlap at debian-x86_64, incomparable
    with pytest.raises(AmbiguityError) as ei:
        check_component('oops', bad, cascade)
    assert 'oops' in str(ei.value) and 'debian' in str(ei.value)


# -- versioned requires: unsatisfiable-constraint lint --------------------

def _v(name, spec):
    return Component(name, spec)


def _cuda_providers():
    return [_v('cuda-toolkit-11', {'provides': {'cuda-toolkit': 11}, 'install': [{'via': 'native'}]}),
            _v('cuda-toolkit-12', {'provides': {'cuda-toolkit': 12}, 'install': [{'via': 'native'}]})]


def _uc(components, cascade):
    from configsys.routecheck import validate
    return [i for i in validate(components, cascade, {}) if i.kind == 'unsatisfiable-constraint']


def test_unsatisfiable_version_constraint_names_the_available_versions(cascade):
    comps = {c.name: c for c in _cuda_providers()
             + [_v('needs13', {'requires': {'cuda-toolkit': '>=13'}, 'install': [{'via': 'native'}]})]}
    uc = _uc(comps, cascade)
    assert len(uc) == 1 and uc[0].component == 'needs13' and uc[0].severity == 'warning'
    assert "cuda-toolkit '>=13'" in uc[0].message and 'have: 11, 12' in uc[0].message


def test_satisfiable_version_constraint_is_clean(cascade):
    comps = {c.name: c for c in _cuda_providers()
             + [_v('needs12', {'requires': {'cuda-toolkit': '>=12'}, 'install': [{'via': 'native'}]})]}
    assert _uc(comps, cascade) == []                       # 12 meets >=12


def test_binding_level_constraint_is_also_checked(cascade):
    comps = {c.name: c for c in _cuda_providers() + [_v('app', {'install': [
        {'via': 'native'}, {'via': 'source', 'requires': {'cuda-toolkit': '<10'}}]})]}
    uc = _uc(comps, cascade)
    assert len(uc) == 1 and 'via:source' in uc[0].message and 'have: 11, 12' in uc[0].message


def test_floor_provider_never_reads_as_unsatisfiable(cascade):
    # a rustup-style provider declares a FLOOR (`cargo >=1.80`, installs the LATEST): an upward
    # require is always satisfiable, so the lint must ABSTAIN rather than flag a false impossibility.
    comps = {c.name: c for c in [
        _v('rustup', {'provides': {'cargo': '>=1.80'}, 'install': [{'via': 'native'}]}),
        _v('mybin', {'requires': {'cargo': '>=1.95'}, 'install': [{'via': 'native'}]})]}
    assert _uc(comps, cascade) == []


# -- provider-pin vs version constraint -----------------------------------

def test_pin_constraint_conflict_flags_and_clears(cascade):
    from configsys.routecheck import pin_constraint_conflicts
    comps = {c.name: c for c in _cuda_providers() + [
        _v('cudnn-8', {'requires': {'cuda-toolkit': '<12'}, 'install': [{'via': 'native'}]})]}
    valid_via = {'native', 'parts'}
    # pin cuda-toolkit -> the 12 provider while cudnn-8 requires <12: a real conflict
    msgs = pin_constraint_conflicts({'cuda-toolkit': 'cuda-toolkit-12'}, comps, valid_via)
    assert len(msgs) == 1 and 'cudnn-8' in msgs[0] and "cuda-toolkit '<12'" in msgs[0]
    # pin to the 11 provider instead: cudnn-8's <12 is satisfied -> clean
    assert pin_constraint_conflicts({'cuda-toolkit': 'cuda-toolkit-11'}, comps, valid_via) == []
    # a binding-pin (value is a via, not a component) is not a provider-pin -> ignored
    assert pin_constraint_conflicts({'cudnn-8': 'native'}, comps, valid_via) == []


def test_disjoint_bindings_are_fine(cascade):
    check_component('ok', _component('ok', 'fedora', 'arch'), cascade)


def test_same_via_overlapping_incomparable_still_raises(cascade):
    # two native bindings that overlap incomparably: which variant of native wins is undefined,
    # and only when: can fix it -> still a hard load error, message names the shared via
    bad = _component('oops', 'cpu: x86_64', 'debian')     # both via: native
    with pytest.raises(AmbiguityError) as ei:
        check_component('oops', bad, cascade)
    assert 'via:native' in str(ei.value)


def test_cross_via_overlapping_incomparable_is_now_allowed(cascade):
    # native (any) + flatpak (any) overlap everywhere and are incomparable — under the multi-
    # method model that's LEGAL (the preference channel picks the default), no longer an error
    both = Component('browser', {'install': [
        {'via': 'native'}, {'via': 'flatpak', 'app': 'org.x.B'}]})
    check_component('browser', both, cascade)             # must not raise


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


# -- the full lint: validate() -------------------------------------------

def _comp(name, spec):
    from configsys.routes import Component
    c = Component(name, spec)
    c.source = 'routes.hu'
    return c


def _validate(cascade, extra):
    '''Run validate() over the real components plus some hand-built extras.'''
    from configsys import routes, routecheck
    _c, components, drivers, _co = routes.load(
        os.path.join(os.path.dirname(__file__), '..', 'routes.hu'), validate=False)
    for name, comp in extra.items():
        components[name] = comp
    return routecheck.validate(components, cascade, drivers)


def test_validate_clean_routes_has_no_issues(cascade):
    from configsys import routes, routecheck
    _c, components, drivers, _co = routes.load(
        os.path.join(os.path.dirname(__file__), '..', 'routes.hu'), validate=False)
    assert routecheck.validate(components, cascade, drivers) == []


def _kinds(issues, name):
    return {i.kind for i in issues if i.component == name}


def test_validate_flags_unknown_via(cascade):
    issues = _validate(cascade, {'x': _comp('x', {'install': [{'via': 'nosuchpm'}]})})
    assert 'unknown-via' in _kinds(issues, 'x')
    assert any(i.is_error for i in issues if i.component == 'x')


def test_validate_flags_unknown_os_in_when_as_warning(cascade):
    issues = _validate(cascade, {'x': _comp('x', {'install': [{'via': 'native', 'when': 'nosuchos'}]})})
    xs = [i for i in issues if i.component == 'x']
    assert xs and xs[0].kind == 'unknown-os' and not xs[0].is_error


def test_validate_flags_dangling_requires_as_warning(cascade):
    issues = _validate(cascade, {'x': _comp('x', {'requires': 'nope-cap', 'install': [{'via': 'native'}]})})
    xs = [i for i in issues if i.component == 'x']
    assert xs and xs[0].kind == 'dangling-requires' and not xs[0].is_error


def test_validate_survives_a_binding_level_versioned_requires(cascade):
    '''Regression (D3): validate() iterated raw binding `requires:`, so a versioned entry
    `[ { cargo: ">=1.96" } ]` (the versioned-requires shape) yielded a dict and crashed with
    `TypeError: unhashable`. It must read the capability NAME via cap_names, like component-level.'''
    good = _comp('vok', {'install': [{'via': 'native', 'requires': [{'cargo': '>=1.96'}]}]})
    issues = _validate(cascade, {'vok': good})       # must not raise
    assert 'dangling-requires' not in _kinds(issues, 'vok')   # cargo IS providable
    bad = _comp('vbad', {'install': [{'via': 'native', 'requires': [{'nope-cap': '>=1'}]}]})
    issues = _validate(cascade, {'vbad': bad})
    assert 'dangling-requires' in _kinds(issues, 'vbad')      # by NAME, still linted


def test_validate_flags_unknown_part(cascade):
    issues = _validate(cascade, {'x': _comp('x', {'install': [{'via': 'parts', 'parts': ['btop', 'ghost']}]})})
    assert 'unknown-part' in _kinds(issues, 'x')


def test_validate_removed_component_provides_nothing(cascade):
    # a `{}` removed component doesn't satisfy a requires (matches resolve-time behavior)
    issues = _validate(cascade, {
        'gone': _comp('gone', {}),
        'x':    _comp('x', {'requires': 'gone', 'install': [{'via': 'native'}]}),
    })
    assert 'dangling-requires' in _kinds(issues, 'x')


def test_validate_warns_on_undecidable_method_tie(cascade):
    # two cross-via methods that overlap AND tie under the default preference (neither ranked,
    # no prefer:) would error at resolve time -> validate() surfaces it as a heads-up warning
    issues = _validate(cascade, {'x': _comp('x', {'install': [{'via': 'cargo'}, {'via': 'gem'}]})})
    xs = [i for i in issues if i.component == 'x' and i.kind == 'method-tie']
    assert xs and not xs[0].is_error and 'prefer' in xs[0].message


def test_validate_no_method_tie_when_preference_decides(cascade):
    # native + flatpak overlap but the default order ranks native above flatpak -> decidable,
    # so NO method-tie warning (only intentional, resolvable alternatives)
    issues = _validate(cascade, {'x': _comp('x', {'install': [
        {'via': 'native'}, {'via': 'flatpak', 'app': 'org.x.B'}]})})
    assert 'method-tie' not in _kinds(issues, 'x')
