'''TUI color config (two-tier model): hex/rgb parsing, palette + per-page role/gradient
resolution, and the config `theme:` deep-merge. Pure functions — no curses.'''

from configsys import layers
from configsys.config import Config
from configsys.tui.theme import (
    ALL_PAGES, BUILTIN_GRADIENTS, DEMO_PAGES, _flag, parse_color, resolve_theme,
)


def test_parse_color_forms():
    assert parse_color('#c88cf0') == (200, 140, 240)
    assert parse_color('#abc') == (0xaa, 0xbb, 0xcc)          # short hex expands
    assert parse_color([90, 200, 120]) == (90, 200, 120)
    assert parse_color('90, 200, 120') == (90, 200, 120)
    assert parse_color('nope') is None and parse_color('#12') is None
    assert parse_color([1, 2]) is None                       # wrong arity


def test_resolve_defaults_reproduce_builtin_look():
    palette, pages = resolve_theme(None)
    assert palette['accent']['fg'] == (200, 140, 240)        # raw color as an fg-only style
    assert palette['component'] == {'fg': (235, 235, 235), 'bold': True}
    assert palette['label']['bg'] == (200, 140, 240)         # composite: fg + bg
    assert palette['footer'].get('reverse') is True
    # every page present with its own default gradient; components is the built-in purple
    assert set(pages) == set(ALL_PAGES)
    ga, gb, gs, enabled = pages['components']['grad']
    assert (ga, gb, gs) == BUILTIN_GRADIENTS['components'] and enabled
    # the whims: pages differ in gradient
    assert pages['profiles']['grad'][0] != pages['components']['grad'][0]


def test_palette_override_and_new_entry():
    palette, _ = resolve_theme({'palette': {
        'accent': {'fg': '#010203'},          # override a built-in
        'ink': {'fg': '#dcdcdc', 'bg': '#222222', 'bold': True},   # a brand-new named style
    }})
    assert palette['accent']['fg'] == (1, 2, 3)
    assert palette['ink'] == {'fg': (220, 220, 220), 'bg': (34, 34, 34), 'bold': True}


def test_palette_effect_toggles_and_bg_clear():
    palette, _ = resolve_theme({'palette': {
        'component': {'bold': False, 'underline': True},   # drop a default flag, add another
        'label': {'bg': ''},                               # clear the built-in bg
    }})
    assert 'bold' not in palette['component'] and palette['component']['underline'] is True
    assert 'bg' not in palette['label']


def test_bare_color_shorthand_sets_fg():
    palette, _ = resolve_theme({'palette': {'accent': '#00ff00'}})
    assert palette['accent']['fg'] == (0, 255, 0)


def test_page_roles_and_zebra_list():
    _, pages = resolve_theme({'pages': {'components': {
        'roles': {'component': ['ink', 'ink_dim'], 'menu_header': 'header'}}}})
    assert pages['components']['roles']['component'] == ['ink', 'ink_dim']
    assert pages['components']['roles']['menu_header'] == 'header'


def test_page_gradient_override_and_disable():
    _, pages = resolve_theme({'pages': {
        'profiles': {'gradient': {'from': '#010203', 'enabled': False}},
        'plugins': {'gradient': False},
    }})
    ga, _gb, _gs, enabled = pages['profiles']['grad']
    assert ga == (1, 2, 3) and enabled is False
    assert pages['plugins']['grad'][3] is False              # gradient: false disables


def test_flag_treats_humon_string_bools_correctly():
    assert _flag('true') and _flag(True) and _flag('yes') and _flag('1')
    assert not _flag('false') and not _flag(False) and not _flag(None) and not _flag('no')


def _cfg(*texts):
    roles = ['repo'] + ['user'] * (len(texts) - 1)
    return Config([layers.Layer(f'l{i}.hu', roles[i], layers.materialize_string(t))
                   for i, t in enumerate(texts)])


def test_config_theme_deep_merge_across_layers():
    c = _cfg(
        '{ theme: { palette: { accent: { fg: "#111111" } }'
        '          pages: { components: { gradient: { from: "#0a0a0a" } } } } }',
        '{ theme: { palette: { accent: { bold: true }  ink: { fg: "#dcdcdc" } }'
        '          pages: { components: { gradient: { to: "#020202" }'
        '                                 roles: { component: ink } } }'
        '          splash: liquid } }',
    )
    t = c.theme()
    # accent merged across layers (fg from repo, bold from user); ink added. NB: humon materializes
    # `true` as the string 'true' in raw data — resolve_theme's _flag normalizes it (asserted below).
    assert t['palette']['accent'] == {'fg': '#111111', 'bold': 'true'}
    assert t['palette']['ink'] == {'fg': '#dcdcdc'}
    # page gradient keys merged from both layers; role from the user layer
    grad = t['pages']['components']['gradient']
    assert grad['from'] == '#0a0a0a' and grad['to'] == '#020202'
    assert t['pages']['components']['roles']['component'] == 'ink'
    assert t['splash'] == 'liquid'
    # and it resolves without error
    palette, pages = resolve_theme(t)
    assert palette['accent'] == {'fg': (17, 17, 17), 'bold': True}
    assert pages['components']['grad'][0] == (10, 10, 10)


def test_demo_pages_are_the_five_content_screens():
    assert DEMO_PAGES == ['components', 'profiles', 'plugins', 'dotfiles', 'config']
    assert 'theme' in ALL_PAGES and 'theme' not in DEMO_PAGES
