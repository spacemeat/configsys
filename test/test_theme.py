'''TUI color config: hex/rgb parsing, theme-override resolution, and the config `theme:` merge.
Pure functions — no curses.'''

from configsys.tui.theme import GRAD_A, SEL_BG, SEMANTIC, parse_color, resolve_theme


def test_parse_color_forms():
    assert parse_color('#c88cf0') == (200, 140, 240)
    assert parse_color('#abc') == (0xaa, 0xbb, 0xcc)          # short hex expands
    assert parse_color([90, 200, 120]) == (90, 200, 120)
    assert parse_color('90, 200, 120') == (90, 200, 120)
    assert parse_color('nope') is None and parse_color('#12') is None
    assert parse_color([1, 2]) is None                       # wrong arity


def test_resolve_theme_defaults():
    colors, elements, ga, gb, gs, enabled = resolve_theme(None)
    assert colors['accent'] == SEMANTIC['accent'] and ga == GRAD_A and gs == SEL_BG and enabled
    assert elements['profile']['fg'] == 'accent'             # default element style


def test_resolve_theme_overrides_colors_elements_and_gradient():
    colors, elements, ga, _gb, gs, enabled = resolve_theme({
        'colors': {'accent': '#010203', 'nope-name': '#ffffff'},
        'elements': {'profile': {'fg': '#abcdef', 'underline': True}, 'bogus': {'fg': '#fff'}},
        'gradient': {'from': '#0a0b0c', 'selected': [1, 2, 3]},
    })
    assert colors['accent'] == (1, 2, 3)                     # color override applied
    assert 'nope-name' not in colors                         # only known semantics
    assert elements['profile'] == {'fg': '#abcdef', 'bold': True, 'underline': True}  # merged
    assert 'bogus' not in elements                           # only known elements
    assert ga == (10, 11, 12) and gs == (1, 2, 3) and enabled


def test_resolve_theme_gradient_can_be_disabled():
    assert resolve_theme({'gradient': False})[5] is False
    assert resolve_theme({'gradient': {'enabled': False}})[5] is False
    assert resolve_theme({'gradient': {'from': '#000000'}})[5] is True
