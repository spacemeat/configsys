from configsys import osversion as ov


def test_parse_version():
    assert ov.parse_version('22.04') == (22, 4)
    assert ov.parse_version('12') == (12,)
    assert ov.parse_version('24.04.1') == (24, 4, 1)
    assert ov.parse_version('') is None
    assert ov.parse_version(None) is None
    assert ov.parse_version((20, 4)) == (20, 4)   # already a tuple


def test_split_qualifier():
    assert ov.split_qualifier('ubuntu@<23.04') == ('ubuntu', '<23.04')
    assert ov.split_qualifier('ubuntu') == ('ubuntu', None)
    assert ov.split_qualifier('pop_os!') == ('pop_os!', None)


def test_parse_constraint_and_satisfies():
    lt = ov.parse_constraint('<23.04')
    assert ov.satisfies(lt, (22, 4)) is True
    assert ov.satisfies(lt, (23, 4)) is False
    assert ov.satisfies(lt, (24, 4)) is False

    ge = ov.parse_constraint('>=24.04')
    assert ov.satisfies(ge, (24, 4)) is True
    assert ov.satisfies(ge, (22, 4)) is False

    exact = ov.parse_constraint('22.04')
    assert ov.satisfies(exact, (22, 4)) is True
    assert ov.satisfies(exact, (22, 10)) is False

    rng = ov.parse_constraint('>=20.04,<23.04')
    assert ov.satisfies(rng, (20, 4)) is True
    assert ov.satisfies(rng, (22, 4)) is True
    assert ov.satisfies(rng, (23, 4)) is False
    assert ov.satisfies(rng, (18, 4)) is False


def test_unknown_version_never_satisfies():
    assert ov.satisfies(ov.parse_constraint('<23.04'), None) is False


def test_debian_and_ubuntu_numbers_do_not_collide_under_the_older_pattern():
    # ubuntu 22.04 must NOT satisfy a debian "<12" variant (the whole reason the
    # base=modern / @<older pattern is safe across the cascade).
    assert ov.satisfies(ov.parse_constraint('<12'), (22, 4)) is False
    assert ov.satisfies(ov.parse_constraint('<12'), (11,)) is True


def test_specificity_ordering():
    assert ov.specificity(ov.parse_constraint('22.04')) == 3        # exact
    assert ov.specificity(ov.parse_constraint('>=20.04,<23.04')) == 2  # bounded
    assert ov.specificity(ov.parse_constraint('<23.04')) == 1       # open
    assert ov.specificity(None) == 0
