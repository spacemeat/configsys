'''TUI install-method picker (Phase 3b) + the pre-Phase-4 fixes: an in-place curses popup (no
drop to the terminal), promote messages deferred to exit, partial requery, and the scroll-offset
fix (cursor no longer pinned to the bottom row). Curses drawing is stubbed; the write path,
choice logic, scroll math, and partial-inspect are what's exercised.'''

from configsys import plugins
from configsys.app import Context, build_parser
from configsys.tui import menu
from configsys.tui.menu import COMPONENT, PROFILE, UNIT, Node, _row_component, _scroll_top


class _Scr:                                  # minimal fake curses screen for the popup loop
    def __init__(self, keys):
        self._keys = list(keys)

    def getmaxyx(self):
        return (24, 80)

    def addstr(self, *a):
        pass

    def refresh(self):
        pass

    def getch(self):
        return self._keys.pop(0)


class _Pal:
    def get(self, _name):
        return 0


def _ctx(tmp_path, *extra):
    args = build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', *extra, 'inspect'])
    return Context(args)


def _menu_on(ctx, component):
    cfg, _r, _u, _l, states = ctx.load_pipeline()
    ms = menu.MenuState(states, menu._profile_comps(cfg))
    ms.cursor = next(i for i, n in enumerate(ms.rows) if _row_component(n) == component)
    return ms


def _steam_home(tmp_path):
    d = tmp_path / '.config' / 'configsys'
    d.mkdir(parents=True)
    (d / 'configsys.hu').write_text(
        '{ configs: [ games ]  profiles: { games: [ steam, btop, zsh ] } }')
    return d


# -- node-id parsing + scroll math (pure) ---------------------------------

def test_row_component_parses_node_ids():
    assert _row_component(Node(COMPONENT, 'c:games:steam', 'steam', 1, [])) == 'steam'
    assert _row_component(Node(UNIT, 'u:games:steam:apt\\steam', 'steam', 2, [])) == 'steam'
    assert _row_component(Node(PROFILE, 'p:games', 'games', 0, [])) is None
    assert _row_component(None) is None


def test_scroll_top_keeps_cursor_free_until_the_edge():
    # cursor inside the window: no scroll (cursor is NOT pinned to the bottom)
    assert _scroll_top(3, 0, 10, 50) == 0
    assert _scroll_top(9, 0, 10, 50) == 0            # last visible row, still no scroll
    # crossing the bottom edge scrolls by one
    assert _scroll_top(10, 0, 10, 50) == 1
    # scrolling back up above the window pulls it up
    assert _scroll_top(5, 20, 10, 50) == 5
    # never past the end: the last page shows fully
    assert _scroll_top(49, 45, 10, 50) == 40
    # short list: no scroll
    assert _scroll_top(2, 0, 10, 5) == 0


# -- the write path (curses-free) -----------------------------------------

def test_apply_method_pin_writes_and_defers_hint(tmp_path):
    cfgdir = _steam_home(tmp_path)
    ctx = _ctx(tmp_path)
    changed, note, deferred = menu._apply_method_pin(ctx, 'steam', 'flatpak', already_pinned=False)
    assert changed and 'flatpak' in note
    assert deferred and 'promote' in deferred        # promote hint deferred to exit, not printed now
    assert plugins.read_pins(str(cfgdir / 'configsys.hu')) == {'steam': 'flatpak'}


def test_apply_method_pin_already_pinned_is_noop(tmp_path):
    _steam_home(tmp_path)
    ctx = _ctx(tmp_path)
    changed, _note, deferred = menu._apply_method_pin(ctx, 'steam', 'flatpak', already_pinned=True)
    assert not changed and deferred is None


def test_apply_method_pin_pretend_does_not_write(tmp_path):
    cfgdir = _steam_home(tmp_path)
    ctx = _ctx(tmp_path, '--pretend')
    changed, note, deferred = menu._apply_method_pin(ctx, 'steam', 'flatpak', already_pinned=False)
    assert not changed and '[pretend]' in note and deferred is None
    assert plugins.read_pins(str(cfgdir / 'configsys.hu')) == {}


# -- the popup glue (fake screen driving getch) ---------------------------

def test_pick_method_popup_selects_and_writes(tmp_path):
    cfgdir = _steam_home(tmp_path)
    ctx = _ctx(tmp_path)
    ms = _menu_on(ctx, 'steam')                      # candidates: native (default) + flatpak
    scr = _Scr([ord('j'), ord('\n')])               # move down to flatpak, enter
    changed, note, deferred = menu._pick_method(scr, _Pal(), ms, ctx)
    assert changed and 'flatpak' in note and 'promote' in deferred
    assert plugins.read_pins(str(cfgdir / 'configsys.hu')).get('steam') == 'flatpak'


def test_pick_method_popup_esc_cancels(tmp_path):
    cfgdir = _steam_home(tmp_path)
    ctx = _ctx(tmp_path)
    ms = _menu_on(ctx, 'steam')
    changed, _note, _d = menu._pick_method(_Scr([27]), _Pal(), ms, ctx)   # esc
    assert not changed
    assert plugins.read_pins(str(cfgdir / 'configsys.hu')) == {}


def test_pick_method_single_method_is_a_noop(tmp_path):
    _steam_home(tmp_path)
    ctx = _ctx(tmp_path)
    ms = _menu_on(ctx, 'zsh')                         # native-only here: no popup, no getch
    changed, note, _d = menu._pick_method(_Scr([]), _Pal(), ms, ctx)
    assert not changed and 'only one install method' in note


# -- partial requery ------------------------------------------------------

def test_fail_detail_surfaces_the_reason():
    from configsys.runner import Result
    r = Result('cmd', 1, stderr='E: could not get lock\nsome trailing line')
    assert menu._fail_detail(r) == 'exit 1: some trailing line'
    # falls back to the tee'd tail of streamed output when there is no stderr
    r2 = Result('cmd', 2, captured='downloading...\ncurl: (22) 404')
    assert menu._fail_detail(r2) == 'exit 2: curl: (22) 404'
    # bare exit code when there is no output at all
    assert menu._fail_detail(Result('cmd', 1)) == 'exit 1'
    assert menu._fail_detail(None) == 'no result'


def test_row_error_not_smeared_onto_profiles(tmp_path):
    # a failed shared dep (curl, required by every tarball) must not paint "install failed" on
    # every profile row — only its component/unit rows carry it
    cfgdir = tmp_path / '.config' / 'configsys'
    cfgdir.mkdir(parents=True)
    (cfgdir / 'configsys.hu').write_text(
        '{ configs: [ a, b ]  profiles: { a: [ lazygit ]  b: [ nushell ] } }')
    ctx = _ctx(tmp_path)
    cfg, _r, _u, _l, states = ctx.load_pipeline()
    ms = menu.MenuState(states, menu._profile_comps(cfg))
    curl_key = next(k for k in states if k.endswith('\\curl'))
    ms.errors = {curl_key: 'install failed: exit 1'}
    prof = [n for n in ms.rows if n.kind == PROFILE]
    assert prof and all(ms.row_error(n) is None for n in prof)     # no smear on profiles
    # but the failure is still visible where it's local (a component/unit that pulls curl)
    assert any(ms.row_error(n) for n in ms._all_nodes() if n.kind != PROFILE)


def test_partial_inspect_reuses_and_reprobes(tmp_path):
    from configsys.installState import InstallState, ComponentState
    from configsys.componentObj import ResolvedComponent
    from configsys.runner import Runner

    def _st(key):
        rc = ResolvedComponent(key=key, driver=key.split('\\')[0], comp=key.split('\\')[1])
        return rc, ComponentState(component=rc, supported=True, present=True,
                                  installed_version='1', latest_version='1', locked=False,
                                  lock_source=None, managed=True, error=None)

    rc_a, st_a = _st('apt\\a')
    rc_b, st_b = _st('apt\\b')
    probed = []
    inst = InstallState(Runner(pretend=True))
    inst.inspect_one = lambda rc: (probed.append(rc.key), st_a)[1]   # spy
    # reuse both; mark only a dirty -> a is re-probed, b is reused untouched
    out = inst.inspect({'apt\\a': rc_a, 'apt\\b': rc_b},
                       reuse={'apt\\a': st_a, 'apt\\b': st_b}, dirty={'apt\\a'})
    assert probed == ['apt\\a']                        # only the dirty one hit the driver
    assert out['apt\\b'] is st_b                        # b's cached state reused as-is


def test_methods_line_lists_eligible_drivers(tmp_path):
    _steam_home(tmp_path)                             # steam: native + flatpak on pop
    ctx = _ctx(tmp_path)
    ms = _menu_on(ctx, 'steam')
    line = menu._methods_line(ms, ctx)
    assert 'native' in line and 'flatpak' in line and '*' in line   # all methods, default marked
    assert '(m to change)' in line


def test_methods_line_blank_when_no_choice(tmp_path):
    _steam_home(tmp_path)
    ctx = _ctx(tmp_path)
    assert menu._methods_line(_menu_on(ctx, 'zsh'), ctx) == ''   # native-only: no line
