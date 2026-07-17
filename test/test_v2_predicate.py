'''Unit tests for the v2 when: DSL — parse, evaluate, scale safety, specificity.'''

from configsys.v2.predicate import Context, Os, ALWAYS, most_specific, parse

SR = {'ubuntu', 'debian', 'fedora'}
POP = Context(['pop_os!', 'ubuntu', 'debian', 'linux'], '22.04', 'x86_64', SR)
UBU = Context(['ubuntu', 'debian', 'linux'], '24.04', 'x86_64', SR)
DEB11 = Context(['debian', 'linux'], '11', 'aarch64', SR)
FED = Context(['fedora', 'linux'], '41', 'x86_64', SR)
ARCH = Context(['arch', 'linux'], '20260101', 'x86_64', SR)


def ev(expr, ctx):
    return parse(expr).eval(ctx)


def test_bare_os_is_subtree_membership():
    assert [ev('debian', c) for c in (POP, UBU, DEB11, FED)] == [True, True, True, False]


def test_exact_leaf():
    assert ev('pop_os!', POP) and not ev('pop_os!', UBU)


def test_guarded_not_carves_out_a_member():
    # the snaps case: bare Ubuntu but not Pop
    assert not ev('ubuntu and not pop_os!', POP)
    assert ev('ubuntu and not pop_os!', UBU)


def test_versioned_atom_on_own_scale():
    assert ev('ubuntu < 23.04', POP)          # Pop 22.04 is on ubuntu's scale
    assert not ev('ubuntu < 23.04', UBU)      # Ubuntu 24.04


def test_version_scale_safety():
    # debian's integer scale must never leak onto Pop (which is on ubuntu's scale)
    assert ev('debian < 12', DEB11)
    assert not ev('debian < 12', POP)


def test_cpu_atom():
    assert ev('cpu: aarch64', DEB11) and not ev('cpu: aarch64', POP)
    assert ev('cpu: [ x86_64, aarch64 ]', POP)


def test_or_and_parens():
    assert [ev('(fedora or arch) and cpu: x86_64', c) for c in (FED, ARCH, POP)] \
        == [True, True, False]


def test_empty_when_is_always_true():
    assert parse(None).eval(ARCH) and parse('').eval(POP)


def test_specificity_prefers_narrow():
    import os
    from configsys.v2 import routes2
    cascade, _c, _m = routes2.load(os.path.join(os.path.dirname(__file__), '..', 'routes2.hu'))
    assert most_specific([Os('pop_os!'), ALWAYS], cascade) is not ALWAYS


def test_bad_syntax_raises():
    import pytest
    from configsys.v2.predicate import PredicateError
    with pytest.raises(PredicateError):
        parse('ubuntu and')
    with pytest.raises(PredicateError):
        parse('(debian or arch')
