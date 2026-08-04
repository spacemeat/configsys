'''TUI color config (color map + per-page role styles): hex/rgb parsing, resolution, and the
config `theme:` deep-merge. Pure functions — no curses.'''

from configsys import layers
from configsys.config import Config
from configsys.tui.theme import (
    ALL_PAGES, BUILTIN_GRADIENTS, COLOR_MAP, DEMO_PAGES, PAGE_ROLES, _flag, full_snapshot,
    parse_color, resolve_theme,
)


def test_parse_color_forms():
    assert parse_color('#c88cf0') == (200, 140, 240)
    assert parse_color('#abc') == (0xaa, 0xbb, 0xcc)          # short hex expands
    assert parse_color([90, 200, 120]) == (90, 200, 120)
    assert parse_color('90, 200, 120') == (90, 200, 120)
    assert parse_color('nope') is None and parse_color('#12') is None


def test_resolve_defaults_reproduce_builtin_look():
    colors, pages = resolve_theme(None)
    assert colors['accent'] == COLOR_MAP['accent']           # the shared map, unmodified
    # a role resolves its fg reference against the map
    comp = pages['components']['roles']['component']
    assert comp == {'fg': (235, 235, 235), 'bg': None, 'bold': True, 'underline': False,
                    'reverse': False}
    label = pages['components']['roles']['label']
    assert label['fg'] == COLOR_MAP['title'] and label['bg'] == COLOR_MAP['accent']   # fg+bg refs
    assert set(pages) == set(ALL_PAGES)
    ga, gb, enabled = pages['components']['grad']
    assert (ga, gb) == BUILTIN_GRADIENTS['components'] and enabled
    assert pages['profiles']['grad'][0] != pages['components']['grad'][0]   # per-page hues differ


def test_color_map_override_and_new_name():
    colors, pages = resolve_theme({
        'colors': {'accent': '#010203', 'brand': '#ffffff'},          # override + a new map color
        'pages': {'components': {'profile': {'fg': 'brand'}}}})        # a role references the new one
    assert colors['accent'] == (1, 2, 3) and colors['brand'] == (255, 255, 255)
    assert pages['components']['roles']['profile']['fg'] == (255, 255, 255)


def test_role_fg_bg_literal_and_effects():
    _c, pages = resolve_theme({'pages': {'components': {
        'component': {'fg': '#abcdef', 'bg': 'accent', 'bold': False, 'underline': True}}}})
    comp = pages['components']['roles']['component']
    assert comp['fg'] == (0xab, 0xcd, 0xef)                  # a literal fg
    assert comp['bg'] == COLOR_MAP['accent']                 # a map-name bg
    assert comp['bold'] is False and comp['underline'] is True   # dropped default bold, added undl


def test_role_override_is_per_page():
    _c, pages = resolve_theme({'pages': {'profiles': {'component': {'fg': 'error'}}}})
    assert pages['profiles']['roles']['component']['fg'] == COLOR_MAP['error']
    assert pages['components']['roles']['component']['fg'] == COLOR_MAP['title']   # other page untouched


def test_selection_bg_drives_the_selected_bar():
    _c, pages = resolve_theme({'pages': {'components': {'selection': {'bg': '#123456'}}}})
    assert pages['components']['sel_bg'] == (0x12, 0x34, 0x56)


def test_gradient_endpoint_references_color_map():
    # a gradient endpoint may name a map color (like a role fg) or be a literal
    _c, pages = resolve_theme({'colors': {'sky': '#0a0b0c'},
                               'pages': {'components': {'gradient': {'from': 'sky', 'to': '#010203'}}}})
    ga, gb, _en = pages['components']['grad']
    assert ga == (10, 11, 12)          # 'from' followed the map color 'sky'
    assert gb == (1, 2, 3)             # 'to' is a literal


def test_page_gradient_override_and_disable():
    _c, pages = resolve_theme({'pages': {
        'profiles': {'gradient': {'from': '#010203', 'enabled': False}},
        'plugins': {'gradient': False}}})
    ga, _gb, enabled = pages['profiles']['grad']
    assert ga == (1, 2, 3) and enabled is False
    assert pages['plugins']['grad'][2] is False


def test_flag_treats_humon_string_bools_correctly():
    assert _flag('true') and _flag(True) and _flag('yes') and _flag('1')
    assert not _flag('false') and not _flag(False) and not _flag(None) and not _flag('no')


def _cfg(*texts):
    roles = ['repo'] + ['user'] * (len(texts) - 1)
    return Config([layers.Layer(f'l{i}.hu', roles[i], layers.materialize_string(t))
                   for i, t in enumerate(texts)])


def test_config_theme_deep_merge_across_layers():
    c = _cfg(
        '{ theme: { colors: { accent: "#111111" }'
        '          pages: { components: { component: { fg: accent }'
        '                                 gradient: { from: "#0a0a0a" } } } } }',
        '{ theme: { colors: { brand: "#dcdcdc" }'
        '          pages: { components: { component: { bold: true }'
        '                                 gradient: { to: "#020202" } } }'
        '          splash: liquid } }',
    )
    t = c.theme()
    assert t['colors'] == {'accent': '#111111', 'brand': '#dcdcdc'}       # map merged across layers
    # the component role merged from both layers (fg from repo, bold from user)
    assert t['pages']['components']['component'] == {'fg': 'accent', 'bold': 'true'}
    grad = t['pages']['components']['gradient']
    assert grad['from'] == '#0a0a0a' and grad['to'] == '#020202'          # gradient keys merged
    assert t['splash'] == 'liquid'
    # and it resolves without error, the role fg following the overridden map color
    colors, pages = resolve_theme(t)
    assert colors['accent'] == (17, 17, 17)
    assert pages['components']['roles']['component']['fg'] == (17, 17, 17)


def test_demo_pages_are_the_five_content_screens():
    assert DEMO_PAGES == ['components', 'profiles', 'plugins', 'dotfiles', 'config']
    assert 'theme' in ALL_PAGES and 'theme' not in DEMO_PAGES


def test_full_snapshot_is_complete_and_drift_immune():
    snap = full_snapshot({'colors': {'accent': '#010203'},
                          'pages': {'components': {'component': {'fg': 'accent', 'bold': False}}}})
    # every built-in map color is spelled out as a hex (not just the one diff)
    assert set(COLOR_MAP).issubset(snap['colors'])
    assert snap['colors']['accent'] == '#010203' and snap['colors']['title'].startswith('#')
    # every role a page uses is spelled out, plus the gradient endpoints
    for page in DEMO_PAGES:
        for role in PAGE_ROLES[page]:
            assert 'fg' in snap['pages'][page][role]
        assert snap['pages'][page]['gradient']['from'] and snap['pages'][page]['gradient']['to']
    comp = snap['pages']['components']['component']
    assert comp['fg'] == 'accent' and 'bold' not in comp        # the override captured (bold dropped)
    # re-resolving the snapshot reproduces the look (self-contained)
    _c, pages = resolve_theme(snap)
    assert pages['components']['roles']['component']['fg'] == (1, 2, 3)
