'''Component attributes (attrs:) — authored tags + auto-derived companion tags, unioned across
layers, deduped case-insensitively. Data layer only (the Profiles filter UI reads Component.attrs).'''

from configsys import routes


def _comp(spec):
    return routes.Component('x', spec)


def test_attrs_is_a_valid_component_key():
    routes._check_component_keys('x', {'attrs': ['CLI'], 'install': []})   # must not raise


def test_authored_attrs_preserved_with_case():
    c = _comp({'attrs': ['CLI', 'TUI', 'FOSS', 'GNU'], 'install': [{'via': 'native'}]})
    assert c.attrs == ['CLI', 'TUI', 'FOSS', 'GNU']


def test_untagged_component_has_empty_attrs():
    assert _comp({'install': [{'via': 'native'}]}).attrs == []


def test_via_dotfiles_service_font_auto_derive():
    assert _comp({'install': [{'via': 'dotfiles', 'glue': 'x'}]}).attrs == ['dotfiles']
    assert _comp({'requires': 'y', 'install': [{'via': 'service', 'unit': 'y'}]}).attrs == ['service']
    assert _comp({'install': [{'via': 'font'}]}).attrs == ['font']


def test_authored_union_derived_dedup_case_insensitive():
    # authored gui/GUI collapse; the derived `dotfiles` is appended
    c = _comp({'attrs': ['GUI', 'gui', 'FOSS'], 'install': [{'via': 'dotfiles'}]})
    assert c.attrs == ['GUI', 'FOSS', 'dotfiles']


def test_attrs_union_across_layers():
    # a lower layer's tags + a higher layer ADDING one -> union (a plugin can tag a core component)
    chain = [({'attrs': ['CLI', 'FOSS'], 'install': [{'via': 'native'}]}, 'repo'),
             ({'attrs': ['tele'], 'install': []}, 'user')]
    merged = routes._merge_component_chain('x', chain)
    assert merged['attrs'] == ['CLI', 'FOSS', 'tele']


def test_tombstone_clears_attrs():
    chain = [({'attrs': ['CLI'], 'install': [{'via': 'native'}]}, 'repo'),
             ({}, 'user'),                                        # {} tombstone clears everything
             ({'attrs': ['GUI'], 'install': [{'via': 'flatpak', 'app': 'a', 'hub': 'flathub'}]}, 'user')]
    assert routes._merge_component_chain('x', chain)['attrs'] == ['GUI']


# -- the Profiles-page faceted filter (_attr_pass): per-axis OR, cross-axis AND, exclude ----------

from configsys.tui.menu import _attr_pass, _ATTR_AXIS_OF


def test_attr_axes_cover_the_vocabulary():
    for t in ('cli', 'gui', 'sdk', 'daemon', 'foss', 'gnu', 'proprietary', 'tele', 'electron',
              'dotfiles', 'service', 'font'):
        assert t in _ATTR_AXIS_OF, t


def test_faceted_filter_per_axis_or_cross_axis_and():
    assert _attr_pass({'cli', 'foss'}, {'cli', 'tui'}, set())          # interface OR: CLI matches
    assert not _attr_pass({'gui', 'foss'}, {'cli', 'tui'}, set())      # GUI fails the interface axis
    assert _attr_pass({'cli', 'foss'}, {'cli', 'foss'}, set())         # CLI(interface) AND FOSS(license)
    assert not _attr_pass({'cli', 'proprietary'}, {'cli', 'foss'}, set())  # license axis unmet


def test_faceted_filter_exclude_and_empty():
    assert not _attr_pass({'gui', 'proprietary'}, set(), {'proprietary'})
    assert _attr_pass({'gui', 'foss'}, set(), {'proprietary'})
    assert _attr_pass(set(), set(), set())                             # untagged passes an empty filter
    assert not _attr_pass({'dotfiles'}, set(), {'dotfiles'})           # default companion-hide
