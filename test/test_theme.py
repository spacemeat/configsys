'''TUI color config (color map + per-page role styles): hex/rgb parsing, resolution, and the
config `theme:` deep-merge. Pure functions — no curses.'''

from configsys import layers
from configsys.config import Config
from configsys.tui.theme import (
    ALL_PAGES, BASIC_MAP, BUILTIN_GRADIENTS, COLOR_MAP, DEMO_PAGES, PAGE_ROLES, _flag, ansi_name,
    env_color_cap, full_snapshot, parse_ansi, parse_color, resolve_basic, resolve_theme,
)


def test_env_color_cap_clamps_down():
    # NO_COLOR (non-empty) and CONFIGSYS_COLOR resolve a depth CAP; auto/empty/unknown -> None.
    assert env_color_cap({}) is None
    assert env_color_cap({'CONFIGSYS_COLOR': 'auto'}) is None
    assert env_color_cap({'NO_COLOR': '1'}) == 'none'
    assert env_color_cap({'NO_COLOR': ''}) is None                 # empty NO_COLOR is NOT set
    assert env_color_cap({'CONFIGSYS_COLOR': 'nocolor'}) == 'none'
    assert env_color_cap({'CONFIGSYS_COLOR': '16'}) == 'basic16'    # allows the bright slots
    assert env_color_cap({'CONFIGSYS_COLOR': '8'}) == 'basic8'      # forces the base 8
    assert env_color_cap({'CONFIGSYS_COLOR': '256'}) == '256'
    assert env_color_cap({'CONFIGSYS_COLOR': 'truecolor'}) == 'truecolor'
    assert env_color_cap({'CONFIGSYS_COLOR': '24bit'}) == 'truecolor'
    assert env_color_cap({'NO_COLOR': 'x', 'CONFIGSYS_COLOR': '256'}) == 'none'   # NO_COLOR wins


def test_resolve_effects_priority(monkeypatch):
    import types
    from configsys.tui.menu import resolve_effects
    monkeypatch.setenv('CONFIGSYS_EFFECTS', '')                # so monkeypatch cleans it up at teardown

    def ctx(setting, env):
        return types.SimpleNamespace(config=types.SimpleNamespace(effects=lambda: setting), env=env)

    # --effects (already in the env) wins over the setting and SSH
    monkeypatch.setenv('CONFIGSYS_EFFECTS', 'none')
    assert resolve_effects(ctx('full', {'SSH_TTY': 'x'})) == 'none'
    monkeypatch.delenv('CONFIGSYS_EFFECTS', raising=False)
    # then the `effects:` machine setting
    assert resolve_effects(ctx('reduced', {'SSH_TTY': 'x'})) == 'reduced'
    monkeypatch.delenv('CONFIGSYS_EFFECTS', raising=False)
    # then the auto-default: reduced over SSH, full locally
    assert resolve_effects(ctx(None, {'SSH_CONNECTION': 'x'})) == 'reduced'
    monkeypatch.delenv('CONFIGSYS_EFFECTS', raising=False)
    assert resolve_effects(ctx(None, {})) == 'full'


def test_parse_ansi_forms():
    assert parse_ansi('red') == 1 and parse_ansi('white') == 7
    assert parse_ansi('bright-red') == 9 and parse_ansi('red-bright') == 9
    assert parse_ansi('bright-black') == 8 and parse_ansi('grey') == 8 and parse_ansi('gray') == 8
    assert parse_ansi('bright-grey') == 15
    assert parse_ansi(3) == 3 and parse_ansi('11') == 11
    assert parse_ansi('default') == -1 and parse_ansi('-1') == -1
    assert parse_ansi('nope') is None and parse_ansi(99) is None and parse_ansi(True) is None


def test_ansi_name_is_parse_ansi_inverse():
    for idx in range(-1, 16):
        assert parse_ansi(ansi_name(idx)) == idx


def test_resolve_basic_keys_by_rgb_and_user_wins():
    colors = dict(COLOR_MAP)
    # the built-in hand-tuning: 'error' -> bright-red (9), keyed by error's rgb
    m = resolve_basic({}, colors)
    assert m[COLOR_MAP['error']] == 9 and m[COLOR_MAP['accent']] == 13   # bright-magenta
    # a user override wins, even though 'error' shares its rgb with 'op_remove' (both bright-red)
    m2 = resolve_basic({'colors-basic': {'error': 'yellow'}}, colors)
    assert m2[COLOR_MAP['error']] == 3
    # an unparseable slot or an unknown name is skipped, not an error
    m3 = resolve_basic({'colors-basic': {'error': 'chartreuse', 'bogus': 'red'}}, colors)
    assert m3[COLOR_MAP['error']] == 9 and COLOR_MAP['error'] in m3


def test_full_snapshot_includes_colors_basic():
    snap = full_snapshot({'colors-basic': {'accent': 'cyan'}})
    assert set(BASIC_MAP).issubset(snap['colors-basic'])        # every built-in slot spelled out
    assert snap['colors-basic']['accent'] == 'cyan'             # the override normalized to a name
    assert snap['colors-basic']['error'] == 'bright-red'        # a built-in default preserved


def test_contrast_guard_promotes_invisible_text():
    from configsys.tui.theme import Palette

    class F:                                       # exercise _contrast without a real curses Palette
        _ANSI_LUM = Palette._ANSI_LUM
        _contrast = Palette._contrast

    f8 = F(); f8.have16 = False                    # 8-color
    assert f8._contrast(0, -1) == 7                # black on the (dark) terminal default -> white
    assert f8._contrast(2, -1) == 2                # green already reads on dark -> kept
    assert f8._contrast(-1, -1) == -1              # the terminal's own default fg is left alone
    f16 = F(); f16.have16 = True                   # 16-color: keep the hue where possible
    assert f16._contrast(8, -1) == 8               # bright-black (grey) reads on dark -> kept
    assert f16._contrast(0, -1) == 15              # black -> bright-white
    assert f16._contrast(4, -1) == 12              # dark blue on dark -> BRIGHT blue (hue preserved)


def test_sgr_downconvert_by_depth():
    import types
    from configsys.tui.splash import _sgr_downconvert

    def pal(**kw):
        base = dict(truecolor=False, direct=False, have256=False, have16=False, mono=False)
        base.update(kw)
        return types.SimpleNamespace(**base)

    s = '\x1b[38;2;200;140;240mX\x1b[0m'
    assert _sgr_downconvert(s, pal(truecolor=True)) == s                 # truecolor: untouched
    out = _sgr_downconvert(s, pal(have256=True, have16=True))            # -> xterm-256 index
    assert '38;5;' in out and '38;2;' not in out and out.endswith('X\x1b[0m')
    assert _sgr_downconvert('\x1b[48;2;10;10;10mY', pal()) == '\x1b[40mY'      # near-black bg -> ANSI 40
    assert _sgr_downconvert('\x1b[38;2;40;200;40mZ', pal(have16=True)) == '\x1b[92mZ'  # luminous -> bright-green
    assert _sgr_downconvert('\x1b[38;2;1;2;3mQ\x1b[0m', pal(mono=True)) == '\x1b[mQ\x1b[0m'  # mono: color dropped
    # a cursor-position escape is not an SGR (...m) sequence -> passes through verbatim
    assert _sgr_downconvert('\x1b[5;1H\x1b[38;2;40;200;40mZ', pal()) == '\x1b[5;1H\x1b[32mZ'


def test_rgb_to_basic8_greys_and_hues():
    import curses
    from configsys.tui.theme import rgb_to_basic8
    # greys map to black/white by brightness, not a hue (the old version sent mid-grey to yellow)
    assert rgb_to_basic8(128, 128, 128) == curses.COLOR_WHITE
    assert rgb_to_basic8(60, 60, 60) == curses.COLOR_BLACK
    assert rgb_to_basic8(235, 235, 235) == curses.COLOR_WHITE
    # saturated colors bucket to the correct ANSI hue
    assert rgb_to_basic8(220, 60, 60) == curses.COLOR_RED
    assert rgb_to_basic8(60, 200, 60) == curses.COLOR_GREEN
    assert rgb_to_basic8(230, 180, 40) == curses.COLOR_YELLOW
    assert rgb_to_basic8(60, 60, 220) == curses.COLOR_BLUE
    assert rgb_to_basic8(200, 140, 240) == curses.COLOR_MAGENTA
    assert rgb_to_basic8(90, 190, 205) == curses.COLOR_CYAN


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
