'''TUI color config (color map + per-page role styles): hex/rgb parsing, resolution, and the
config `theme:` deep-merge. Pure functions — no curses.'''

from configsys import layers
from configsys.config import Config
from configsys.tui.theme import (
    ALL_PAGES, BASIC_MAP, BUILTIN_GRADIENTS, COLOR_MAP, DEMO_PAGES, PAGE_ROLES, _truthy, ansi_name,
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
    assert env_color_cap({'NO_COLOR': 'x', 'CONFIGSYS_COLOR': '256'}) == 'none'   # NO_COLOR beats the env
    # an explicit --color / --nocolor (CONFIGSYS_COLOR_FLAG, set by _main) beats both: NO_COLOR is a
    # default a per-run flag overrides (no-color.org); `--color auto` means detect, NO_COLOR or not
    assert env_color_cap({'NO_COLOR': '1', 'CONFIGSYS_COLOR_FLAG': '256'}) == '256'
    assert env_color_cap({'NO_COLOR': '1', 'CONFIGSYS_COLOR_FLAG': 'auto'}) is None
    assert env_color_cap({'CONFIGSYS_COLOR': '256', 'CONFIGSYS_COLOR_FLAG': 'none'}) == 'none'
    assert env_color_cap({'CONFIGSYS_COLOR': '8', 'CONFIGSYS_COLOR_FLAG': '24bit'}) == 'truecolor'


def test_color_flags_hand_off_to_the_cap(monkeypatch):
    # _main turns --color / --nocolor into CONFIGSYS_COLOR_FLAG before anything builds a Palette
    import os
    from configsys import app
    monkeypatch.setenv('NO_COLOR', '1')
    monkeypatch.setenv('CONFIGSYS_COLOR_FLAG', '')                 # so monkeypatch restores it
    for argv, want in ((['--color', '256'], '256'), (['--nocolor'], 'none'), (['--color', 'auto'], None)):
        os.environ['CONFIGSYS_COLOR_FLAG'] = ''
        app._color_flag_handoff(app.build_parser().parse_args(argv + ['inspect']))
        assert env_color_cap() == want, argv


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


def test_resolve_basic_keys_by_name_and_user_wins():
    colors = dict(COLOR_MAP)
    # the built-in hand-tuning: 'error' -> bright-red (9), keyed by the map NAME (tui-theme-13)
    m = resolve_basic({}, colors)
    assert m['error'] == 9 and m['accent'] == 13                       # bright-magenta
    # a user override changes only that name — 'op_remove' shares error's rgb and keeps its slot
    m2 = resolve_basic({'colors-basic': {'error': 'yellow'}}, colors)
    assert m2['error'] == 3 and m2['op_remove'] == 9
    # an unparseable slot or an unknown name is skipped, not an error
    m3 = resolve_basic({'colors-basic': {'error': 'chartreuse', 'bogus': 'red'}}, colors)
    assert m3['error'] == 9 and 'bogus' not in m3


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
                    'reverse': False, 'fg_name': 'title', 'bg_name': None}   # names: the 8/16 slots
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


def test_truthy_treats_humon_string_bools_correctly():
    assert _truthy('true') and _truthy(True) and _truthy('yes') and _truthy('1')
    assert not _truthy('false') and not _truthy(False) and not _truthy(None) and not _truthy('no')


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


def test_demo_pages_are_the_content_screens():
    assert DEMO_PAGES == ['components', 'profiles', 'plugins', 'glue', 'dotfiles', 'config']
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


def test_theme_components_sample_is_stable_and_covers_every_role():
    # The Theme F1 sample uses a SYNTHETIC tree (not the user's real, possibly-empty install set), so
    # every themeable status/element is always visible to colour. It must build with no ctx/data and
    # exercise all statuses + op badges + the profile/component/unit tree.
    from configsys.tui.menu import _sample_components_state, COMPONENT, UNIT, PROFILE
    pm = _sample_components_state()
    kinds = {n.kind for n in pm._all_nodes()}
    assert {PROFILE, COMPONENT, UNIT} <= kinds                       # a real tree, not a flat list
    statuses = {n.status for n in pm._all_nodes() if n.kind in (COMPONENT, UNIT)}
    assert {'installed', 'outdated', 'partial', 'missing', 'locked', 'error', 'unsupported'} <= statuses
    assert {'install', 'upgrade', 'remove', 'lock'} == set(pm.staged.values())   # every op badge
    drivers = {st.component.driver for st in pm.states.values()}
    assert {'apt', 'cargo', 'flatpak', 'tarball', 'appImage'} <= drivers          # varied methods
    assert {'user', 'system'} <= {(st.scope or 'user') for st in pm.states.values()}


def test_theme_glue_and_dotfiles_samples_are_stable_and_cover_states(tmp_path):
    from configsys.app import Context, build_parser
    from configsys.tui import menu
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))
    gs = menu._sample_glue_state(ctx)
    assert {r[3] for r in gs.rows} == {'linked', 'drifted', 'template'}       # active / changed / available
    assert set(gs.loader.values()) == {'loader-on', 'loader-off'}             # wired + not
    assert any(e[0] == 'hdr' for e in gs.display) and gs.rows                 # shell section headers + rows
    ds = menu._sample_dotfiles_state(ctx)
    assert {r[3] for r in ds.rows} == {'linked', 'unmanaged', 'empty'}        # managed / unmanaged / no-config
    assert all(hasattr(r[0], 'comp') for r in ds.rows)                        # _df_cells reads rc.comp


def test_theme_plugins_sample_is_stable_and_covers_states(tmp_path):
    from configsys.app import Context, build_parser
    from configsys.tui import menu
    from configsys import plugins
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))
    pl = menu._sample_plugins_state(ctx)
    assert any(r['primary'] for r in pl.rows)                                 # a ★ primary plugin
    assert {r['code_state'] for r in pl.rows} >= {'trusted', 'changed', 'unsynced', 'none'}
    assert any(not r['abi_ok'] for r in pl.rows) and any(r['abi_ok'] for r in pl.rows)   # error + ok
    assert any(not r['synced'] for r in pl.rows)                             # an unsynced row
    assert any(t['depth'] == 1 for t in pl.tree)                            # a transitive child (tree prefix)
    # a remote-ref AHEAD of the installed ref -> the amber "update available" state
    assert any(isinstance(pl.remote.get(plugins.dir_name(r['source'])), str)
               and pl.remote[plugins.dir_name(r['source'])] != r['ref'] for r in pl.rows)
    assert pl.diff_files and pl.cur_row() is not None                        # a mocked diff + a selection


def test_profiles_page_has_one_orphan_role_after_user_profiles_retired():
    # Only orphan_lurking is actually rendered on the Profiles page (⊙ installed-untracked / ⮾
    # staged-uninstall); excluded/forgotten/foreign were user-profile leftovers and are pruned.
    from configsys.tui.theme import PAGE_ROLES, COLOR_MAP, ROLE_DEFAULTS
    assert [r for r in PAGE_ROLES['profiles'] if 'orphan' in r] == ['orphan_lurking']
    for dead in ('orphan_excluded', 'orphan_forgotten', 'orphan_foreign'):
        assert dead not in COLOR_MAP and dead not in ROLE_DEFAULTS   # fully removed, not just unlisted


def test_theme_profiles_sample_forces_overlay_without_a_scan(tmp_path):
    from configsys.app import Context, build_parser
    from configsys.tui import menu
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))
    ps = menu._sample_profiles_state(ctx)
    assert ps.show_install == 1                               # overlay on -> install-state colours show
    assert ps.overlay() == (frozenset(), {}, frozenset())     # injected empty -> no real orphan scan
    # install_state is ALSO called (name, force=True) / (name, stack, force=True) by the NEW-count path
    # the draw triggers — the override must accept those, or the Profiles draw raises into an empty box.
    assert ps.install_state('x', force=True) in ('all', 'some', 'none')
    assert ps.install_state('x', (), force=True) in ('all', 'some', 'none')
    assert len(ps.visible_pnodes()) > 0                       # a real (never-empty) profile tree
    # a VARIED spread across the whole visible catalog (not the old uniform "everything installed"):
    # multiple distinct install-states, and NEW / flagged / tracked rows all present so every glyph shows.
    vis = [nm for nm, _d in ps._catalog_rows()]
    assert len(vis) >= 12
    assert len({ps.install_state(n) for n in vis}) >= 3       # a mix of all / some / none
    assert any(ps.install_state(n) == 'none' for n in vis)    # most rows not installed (early setup)
    cfg = ps.ctx.config
    assert any(cfg.is_new(n) for n in vis)                    # ◆ NEW rows
    assert cfg.dispositions()                                 # ☆ interesting / · seen rows
    assert cfg.included()                                     # ● tracked rows on this box
    assert any(m in cfg.picks() for m in ('thisbox', 'laptop'))


def test_a_theme_snapshot_keeps_the_theme_page_and_every_overridden_role():
    # review-2026-11-2 B8 (tui-theme-03): export/promote dropped the Theme page and unlisted roles
    from configsys.tui.theme import full_snapshot
    snap = full_snapshot({'pages': {'theme': {'component': {'fg': '#ff0000'}},
                                    'components': {'select_marker': {'fg': '#00ff00'},
                                                   'my_odd_role': {'fg': '#0000ff'}}}})
    assert snap['pages']['theme']['component']['fg'] == '#ff0000'
    assert snap['pages']['components']['select_marker']['fg'] == '#00ff00'
    assert snap['pages']['components']['my_odd_role']['fg'] == '#0000ff'


def test_loading_a_theme_pack_keeps_your_overrides_on_top_unless_reset():
    from configsys.actions import _overlay_theme
    pack = {'colors': {'accent': '#111111', 'title': '#222222'}}
    mine = {'colors': {'accent': '#ffffff'}}
    assert _overlay_theme(pack, mine) == {'colors': {'accent': '#ffffff', 'title': '#222222'}}


def test_every_role_a_screen_paints_is_themeable_on_its_page(tmp_path):
    # B16 / tui-theme-08: PAGE_ROLES (the editor's per-page list, the snapshot set) must cover what
    # each screen actually paints — else a painted role can't be retinted on that page
    from _render_harness import SCREENS, RecordingPalette, build_ctx, _render

    class Rec(RecordingPalette):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.seen = {}

        def _note(self, name):
            self.seen.setdefault(self._page, set()).add(name)

        def style(self, element, *a, **k):
            self._note(element)
            return super().style(element, *a, **k)

        def at(self, name, *a, **k):
            self._note(name)
            return super().at(name, *a, **k)

    ctx = build_ctx(tmp_path)
    for name in SCREENS:
        pal = Rec()
        for size in [(40, 160), (24, 80)]:
            _render(name, ctx, pal, *size)
        for page, painted in pal.seen.items():
            missing = painted - set(PAGE_ROLES.get(page, []))
            assert not missing, f'{name} paints {sorted(missing)} on page {page}, not in PAGE_ROLES'


# -- review-2026-11-2 tui-theme-14 / 16 -----------------------------------------------------------

def test_gradient_off_tokens_are_one_parser():
    import types

    from configsys import actions
    from configsys.tui.theme import is_off
    for v in ['0', 'False', 'OFF', 'no ', False]:
        t = {'pages': {'components': {'gradient': {'enabled': v}}}}
        assert resolve_theme(t)[1]['components']['grad'][2] is False, v
        ctx = types.SimpleNamespace(config=types.SimpleNamespace(theme=lambda t=t: t))
        assert actions.theme_overrides(ctx)['pages']['components']['gradient'] is False, v
        assert resolve_theme({'pages': {'components': {'gradient': v}}})[1]['components']['grad'][2] is False
    for v in [None, True, 'true', 'on', '1', {}]:
        assert not is_off(v)
    assert resolve_theme({'pages': {'components': {'gradient': {'enabled': 'yes'}}}})[1]['components']['grad'][2]
    assert 'enabled' in actions._THEME_BOOL_ATTRS                    # `theme set …enabled 0` stores false


def test_rgb_to_256_is_the_nearest_xterm_entry():
    from configsys.tui.theme import _dist2, rgb_to_256, xterm_rgb
    probes = list(COLOR_MAP.values()) + [(0, 0, 0), (255, 255, 255), (128, 128, 128), (3, 0, 4),
                                         (58, 34, 88), (240, 240, 240), (100, 101, 99)]
    for rgb in probes:
        best = min(_dist2(xterm_rgb(i), rgb) for i in range(16, 256))
        assert _dist2(xterm_rgb(rgb_to_256(*rgb)), rgb) == best, rgb


def test_the_screen_list_has_one_source():
    # tui-theme-21: every per-page table agrees with theme.SCREEN_REGISTRY
    from configsys.tui import paint
    from configsys.tui.keyspec import KNOWN_ACTIONS, SCREEN_IDS, _FALLBACK, _PAGE_N, shipped_keymap
    from configsys.tui.theme import SCREEN_REGISTRY
    ids = [sid for sid, _t, _k in SCREEN_REGISTRY]
    assert ALL_PAGES == ids and DEMO_PAGES == [p for p in ids if p != 'theme']
    assert set(ids) == SCREEN_IDS == {sid for _k, sid, _n in paint.SCREENS}
    assert set(ids) == set(PAGE_ROLES) == set(BUILTIN_GRADIENTS) == set(_FALLBACK['screens'])
    assert {a for a in KNOWN_ACTIONS['theme'] if _PAGE_N.match(a)} == {
        f'page-{i}' for i in range(1, len(ids) + 1)}
    km = shipped_keymap()                                   # config.hu's switcher covers each screen
    assert {sid for sid in ids if km.keys_for('screens', sid)} == set(ids)
    assert {sid for sid in ids if km.keys_for('theme', f'page-{ids.index(sid) + 1}')} == set(ids)
