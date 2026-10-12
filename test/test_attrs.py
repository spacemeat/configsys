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
              'dotfiles', 'glue', 'service', 'font'):
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


# `GNU` means "a GNU project" (docs/component-attrs.md), not "GPL-licensed" — that is `copyleft`.
# Each shipped GNU tag, against the package's entry at gnu.org/software/ (checked 2026-10-12).
# A new GNU tag fails here until it's confirmed against that list; a component that only shares a
# name with a GNU package (Breezy vs GNU Bazaar, Artifex Ghostscript, the MPD client `mpc`) or is
# merely GPL (niri, tree, krita, GNOME — which left GNU) doesn't get one.
_GNU_PROJECTS = {
    'autoconf': 'autoconf', 'automake': 'automake', 'bison': 'bison', 'c-toolchain': 'gcc + make',
    'cpp-toolchain': 'gcc + make', 'emacs': 'emacs', 'gdb': 'gdb', 'gettext': 'gettext',
    'gfortran': 'gcc', 'gimp': 'gimp', 'gnat': 'gnat', 'gnucobol': 'gnucobol', 'gnupg': 'gnupg',
    'gnuradio': 'gnuradio', 'gnustep': 'gnustep', 'guile': 'guile', 'libiberty': 'libiberty',
    'libidn2': 'libidn', 'libstdc++': 'gcc', 'libtool': 'libtool', 'make': 'make', 'mc': 'mc',
    'ncurses': 'ncurses', 'objective-c': 'gcc', 'octave': 'octave', 'patch': 'patch', 'r': 'r',
    'source-highlight': 'src-highlite', 'stow': 'stow', 'wget': 'wget',
    **{f'gcc-{v}': 'gcc' for v in (10, 11, 12, 13, 14, 15)},
}


def test_gnu_tag_marks_exactly_the_gnu_projects(tmp_path):
    from configsys.app import Context, build_parser
    r = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'arch', 'inspect'])).routes
    tagged = {n for n, c in r.components.items() if 'GNU' in (c.attrs or ())}
    assert tagged - set(_GNU_PROJECTS) == set(), 'GNU-tagged but not a known GNU project'
    assert set(_GNU_PROJECTS) - tagged == set(), 'a GNU project lost its GNU tag'
    assert all('FOSS' in r.components[n].attrs for n in tagged)
