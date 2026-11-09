'''Pins for the review-2026-11-2 TUI fixes (tui-core-* / tui-screens-*): headless where possible
(BufferSurface + RecordingPalette), with the router driven through fakes for the session-loop items.'''

import contextlib
import curses
import pathlib
import re
import types

import pytest

from _render_harness import RecordingPalette, build_ctx
from configsys.componentObj import ResolvedComponent
from configsys.installState import ComponentState
from configsys.tui import menu
from configsys.tui.models import UNIT, MenuState
from configsys.tui.surface import BufferSurface

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope='module')
def ctx(tmp_path_factory):
    return build_ctx(tmp_path_factory.mktemp('g8'))


def _state(comp, driver='fakedrv', inst='1', latest='1', **fields):
    rc = ResolvedComponent(key=f'{driver}\\{comp}', driver=driver, comp=comp,
                           fields={'name': comp, **fields}, requested_as={comp})
    return ComponentState(component=rc, supported=True, present=inst is not None,
                          installed_version=inst, latest_version=latest, locked=False,
                          lock_source=None, error=None)


# -- tui-core-11: the dead names stay gone ----------------------------------------------------------

def test_dead_tui_names_are_gone():
    dead = ('node_kind', 'rrows', 'rncols', 'KEY_TO_OP', 'KEY_TO_SCREEN', '_DF_CAPTURE_STATES',
            'IMPLEMENTED', 'CursesSurface', '_with_uninstall_node', '_menu_model', '_node_component',
            'clear_all_staged', 'def relation', 'def is_installed', 'def _pick_method(',
            'def _pick_provider(', 'not built yet')
    for f in (ROOT / 'configsys' / 'tui').rglob('*.py'):
        text = f.read_text()
        for name in dead:
            pat = ((r'\b' if name[0].isalnum() or name[0] == '_' else '') + re.escape(name)
                   + (r'\b' if name[-1].isalnum() else ''))
            assert not re.search(pat, text), \
                f'{name} is back in {f.relative_to(ROOT)}'
    from configsys.tui.screens.base import Intent
    assert not hasattr(Intent(), 'quit')


# -- tui-core-14: the detail line keeps a System Updates row's full versions ------------------------

def test_infoblock_keeps_full_versions_on_a_system_update_row():
    st = _state('libc6', inst='2.39-0ubuntu8.3', latest='2.39-0ubuntu8.4', system_update=True)
    ms = MenuState({st.component.key: st}, [('system', ['libc6'])])
    ms.toggle_expand_all()
    unit = next(n for n in ms.rows if n.kind == UNIT)
    ms.cursor = ms.rows.index(unit)
    line = menu._infoblock(ms, types.SimpleNamespace(runner=None, paths=None))
    assert 'installed: 2.39-0ubuntu8.3' in line and 'latest: 2.39-0ubuntu8.4' in line
    assert unit.installed_str() == '2.39-0ubuntu8.3'          # the columns agree with the detail line
    # an ordinary row still reads the cleaned version
    st2 = _state('fd', inst='v9.0.0', latest='v10.1.0')
    ms2 = MenuState({st2.component.key: st2}, [('user', ['fd'])])
    ms2.toggle_expand_all()
    ms2.cursor = ms2.rows.index(next(n for n in ms2.rows if n.kind == UNIT))
    assert 'installed: 9.0.0' in menu._infoblock(ms2, types.SimpleNamespace(runner=None, paths=None))


# -- tui-core-15: PgDn on Components moves exactly one drawn window ---------------------------------

def test_components_page_down_never_skips_a_row(ctx):
    from configsys.tui.screens.components import ComponentsScreen
    names = [f'c{i:02d}' for i in range(80)]
    states = {f'fakedrv\\{n}': _state(n) for n in names}
    ms = MenuState(states, [('user', names)])
    ms.descriptions = {}
    scr = ComponentsScreen(ctx, ms)
    scr.note, scr.diags = '', ()
    km = menu._KEYMAP
    pgdn = next(k for k in range(0, 1024) if km.action_for('components', k) == 'page-down')
    seen = set()
    surf = BufferSurface(24, 100)
    for _ in range(12):
        vm = scr.render(surf, RecordingPalette(), ctx)
        seen.update(range(vm.top, vm.top + len(vm.rows)))
        scr.handle(pgdn, ctx, surf, None, None, None)
    assert seen == set(range(len(ms.rows)))                  # every row was on screen at some point


# -- the router, driven headless: a fake curses screen, worker and Palette --------------------------

class _KeyScr(BufferSurface):
    '''A BufferSurface that also answers the router's input calls from a scripted key list (an
    exception CLASS in the list is raised from getch, like Ctrl-C would).'''

    def __init__(self, keys, h=30, w=120):
        super().__init__(h, w)
        self.keys = list(keys)

    def getch(self):
        k = self.keys.pop(0)
        if isinstance(k, type) and issubclass(k, BaseException):
            raise k
        return ord(k) if isinstance(k, str) else k

    def timeout(self, _t):
        pass

    def keypad(self, _flag):
        pass


class _FakeScreen:
    '''Stands in for a real screen class: paints nothing; `handle` returns the next scripted Intent.'''
    intents = []

    def __init__(self, ctx):
        self.model = types.SimpleNamespace(dirty=set())

    def render(self, surface, pal, ctx, note=None):
        pass

    def handle(self, ch, ctx, stdscr, pal):
        return self.intents.pop(0)


def _drive(monkeypatch, ctx, keys, intents=(), reload=None, busy=None):
    from configsys import rebootcheck, sysupdates
    from configsys.tui.screens import config as config_screen
    scr = _KeyScr(keys)

    @contextlib.contextmanager
    def fake_curses_screen(*_a, **_k):
        yield scr
    monkeypatch.setattr(menu, 'curses_screen', fake_curses_screen)
    monkeypatch.setattr(curses, 'noecho', lambda: None)
    monkeypatch.setattr(curses, 'cbreak', lambda: None)
    monkeypatch.setattr(menu, 'Palette', lambda _theme: RecordingPalette())
    monkeypatch.setattr(menu, 'resolve_effects', lambda _c: 'none')
    monkeypatch.setattr(menu, '_chosen_splash', lambda _c: (False, None))
    loaded = ctx.load_pipeline()

    class _Worker:
        def __init__(self, _c):
            pass

        def start(self):
            return self

        def join(self):
            return loaded
    monkeypatch.setattr(menu, '_InspectWorker', _Worker)
    monkeypatch.setattr(menu, '_quit_push', lambda *a, **k: (True, []))
    monkeypatch.setattr(sysupdates, 'start_scan', lambda _c: None)
    monkeypatch.setattr(sysupdates, 'scan_busy', lambda _c: False)
    monkeypatch.setattr(sysupdates, 'take_dirty', lambda _c: False)
    monkeypatch.setattr(rebootcheck, 'reboot_pending', lambda _c: (False, ''))
    monkeypatch.setattr(config_screen, 'ConfigScreen', _FakeScreen)
    _FakeScreen.intents = list(intents)
    if reload is not None:
        monkeypatch.setattr(menu, '_reload', reload)
    if busy is not None:
        monkeypatch.setattr(menu, '_busy', busy)
    return menu.run(ctx)


def test_intent_goto_components_rebuilds_like_the_screen_key(ctx, monkeypatch):
    # tui-core-23: a handle's Intent(goto='components') after an edit runs the same entry work
    # (the _reload) as pressing the Components key. tui-core-18: a busy note paints first.
    from configsys.tui.screens.base import Intent
    calls = []

    def fake_reload(c, ms, dirty):
        calls.append('reload')
        return ms, c.config, None, ms.states, []
    _drive(monkeypatch, ctx, ['6', 'z', 'Q'], intents=[Intent(goto='components', dirty=True)],
           reload=fake_reload, busy=lambda _s, _p, msg: calls.append(f'busy:{msg}'))
    assert calls == ['busy:rebuilding…', 'reload']


def test_ctrl_c_still_resumes_the_reporter_and_prints_held_notes(ctx, monkeypatch, capsys):
    # tui-core-26: a KeyboardInterrupt out of the loop still hands the console back and prints what
    # was held for after the TUI.
    from configsys.tui.screens.base import Intent
    with pytest.raises(KeyboardInterrupt):
        _drive(monkeypatch, ctx, ['6', 'z', KeyboardInterrupt],
               intents=[Intent(pending_notes=['ZZ held note'])])
    assert 'configsys: ZZ held note' in capsys.readouterr().out
    assert not ctx.reporter._paused


def test_curses_screen_teardown_reaches_endwin_when_setup_fails(monkeypatch):
    from configsys.tui import screen
    calls = []
    fake = types.SimpleNamespace(keypad=lambda f: calls.append(f'keypad:{f}'))
    monkeypatch.setattr(screen, 'direct_color_setup', lambda **_k: None)
    monkeypatch.setattr(screen.curses, 'initscr', lambda: fake)
    monkeypatch.setattr(screen.curses, 'noecho', lambda: None)

    def bad_cbreak():
        raise curses.error('cbreak')
    monkeypatch.setattr(screen.curses, 'cbreak', bad_cbreak)
    monkeypatch.setattr(screen.curses, 'nocbreak', lambda: (_ for _ in ()).throw(curses.error('x')))
    monkeypatch.setattr(screen.curses, 'curs_set', lambda _v: None)
    monkeypatch.setattr(screen.curses, 'echo', lambda: calls.append('echo'))
    monkeypatch.setattr(screen.curses, 'endwin', lambda: calls.append('endwin'))
    monkeypatch.setattr(screen, '_restore_cr_nl', lambda: calls.append('restore'))
    with pytest.raises(curses.error):
        with screen.curses_screen():
            pytest.fail('setup failed; the body must not run')
    assert calls[-2:] == ['endwin', 'restore'] and 'echo' in calls   # nocbreak raising skipped nothing


# -- tui-core-13: the built direct-colour terminfo never lands in the real home ---------------------

def _fake_direct(monkeypatch, record):
    from configsys.tui import screen, terminfo

    def build(name, term, dirs, out):
        record.append(out)
        pathlib.Path(out, 'x').mkdir(parents=True, exist_ok=True)
        pathlib.Path(out, 'x', name).write_bytes(b'built')
        return True
    monkeypatch.setattr(terminfo, 'build_direct', build)
    monkeypatch.setattr(screen, '_terminfo_exists', lambda *_a, **_k: False)
    monkeypatch.setattr(screen.curses, 'has_extended_color_support', lambda: True, raising=False)
    for k in ('NO_COLOR', 'CONFIGSYS_COLOR', 'CONFIGSYS_COLOR_FLAG', 'TMUX', 'TERMINFO'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv('TERM', 'xterm-256color')
    monkeypatch.setenv('COLORTERM', 'truecolor')
    return screen


def test_terminfo_cache_follows_the_sandbox_home(tmp_path, monkeypatch):
    record = []
    screen = _fake_direct(monkeypatch, record)
    paths = types.SimpleNamespace(env={'CONFIGSYS_HOME': str(tmp_path), 'XDG_CACHE_HOME': '/nope'},
                                  home=tmp_path)
    target = screen.terminfo_cache_dir(paths)
    assert target == str(tmp_path / '.cache' / 'configsys' / 'terminfo')   # XDG ignored under --home
    with screen.direct_color_env(target):
        import os
        assert os.environ['TERMINFO'] == target and os.environ['TERM'] == 'xterm-direct'
    assert record == [target] and (tmp_path / '.cache' / 'configsys' / 'terminfo').is_dir()


def test_terminfo_under_pretend_is_built_in_a_temp_dir_that_goes_away(tmp_path, monkeypatch):
    record = []
    screen = _fake_direct(monkeypatch, record)
    target = str(tmp_path / 'cache')
    with screen.direct_color_env(target, pretend=True):
        import os
        built = os.environ['TERMINFO']
    assert record == [built] and built != target
    assert not pathlib.Path(built).exists()            # removed once curses had read it
    assert not pathlib.Path(target).exists()           # and nothing in the configured cache


# -- tui-core-17 / tui-screens-14: the Profiles per-routes caches follow ctx.routes ------------------

def _routes(parts, requires):
    comps = {'agg': types.SimpleNamespace(parts=list(parts), bindings=[], requires=[]),
             'app': types.SimpleNamespace(parts=[], bindings=[], requires=list(requires))}
    for n in set(parts) | set(requires):
        comps[n] = types.SimpleNamespace(parts=[], bindings=[], requires=[])

    def context():
        raise RuntimeError('no context in this fake')   # _parts falls back to comp.bindings
    return types.SimpleNamespace(components=comps, context=context, cascade=None)


def _bare_ps(routes):
    from configsys.tui.panes import ProfileScreen
    ps = ProfileScreen.__new__(ProfileScreen)
    ps.ctx = types.SimpleNamespace(routes=routes, config=types.SimpleNamespace(pins=lambda: {}))
    ps._parts_cache, ps._hard_dep_cache, ps._avail_os_cache = {}, {}, {}
    ps._caches_routes = None
    return ps


def test_profile_caches_recompute_after_a_routes_swap(monkeypatch):
    from configsys import reportgen
    monkeypatch.setattr(reportgen, 'coverage', lambda c, n: [{'label': f'os-of-{id(c.routes)}', 'ok': True}])
    old = _routes(['p1'], ['libold'])
    ps = _bare_ps(old)
    assert ps._parts('agg') == ['p1'] and ps._hard_deps('app') == frozenset({'libold'})
    first = ps.available_oses('agg')
    new = _routes(['p2', 'p3'], ['libnew'])
    ps.ctx.routes = new                                     # what ctx.invalidate() + a rebuild do
    assert ps._parts('agg') == ['p2', 'p3']
    assert ps._hard_deps('app') == frozenset({'libnew'})
    assert ps.available_oses('agg') != first


def test_probe_in_flight_does_not_repopulate_after_invalidate(monkeypatch):
    import threading
    from configsys import adapt, drivers, resolve
    from configsys.driver import Driver
    from configsys.tui.panes import ProfileScreen
    entered, release = threading.Event(), threading.Event()

    class _Slow(Driver):
        def get_version(self, rc):
            entered.set()
            release.wait(5)
            return '1.0'
    monkeypatch.setattr(resolve, 'candidate_bindings', lambda *a, **k: ['b'])
    monkeypatch.setattr(resolve, 'via_representatives', lambda bs, _c: bs)
    monkeypatch.setattr(resolve, 'unit_for_binding', lambda *a, **k: 'unit')
    monkeypatch.setattr(adapt, 'to_resolved_component', lambda _u: types.SimpleNamespace(driver='slow'))
    monkeypatch.setattr(drivers, 'get_driver', lambda *a, **k: _Slow.__new__(_Slow))
    ps = ProfileScreen.__new__(ProfileScreen)
    routes = types.SimpleNamespace(components={'x': types.SimpleNamespace(bindings=['b'])},
                                   context=lambda: None, cascade=None, block=None, overrides=None)
    ps.ctx = types.SimpleNamespace(routes=routes, runner=None, paths=None)
    ps._overlay = ps._scan_caches = ps._async_overlay = None
    ps._ov_gen = ps._probe_gen = 0
    ps._probe_installed, ps._probe_seen, ps._probe_queue = {}, {'x'}, ['x']
    ps._probe_thread, ps._probe_dirty = None, False
    ps._start_probe()
    assert entered.wait(5)
    ps.invalidate_overlay()                                 # an execute changed what's on disk
    release.set()
    ps._probe_thread.join(5)
    assert ps._probe_installed == {}                        # the stale finding never lands


# -- tui-core-18: the coverage matrix for an unavailable component never runs on the UI thread ------

def test_profiles_unavailable_component_coverage_runs_off_the_ui_thread(ctx, monkeypatch):
    import threading
    import time
    from configsys import reportgen
    from configsys.tui.screens.profiles import ProfilesScreen
    main = threading.current_thread()

    def coverage(c, name):
        assert threading.current_thread() is not main, 'coverage ran on the UI thread'
        return [{'label': 'fedora', 'ok': True}, {'label': 'arch', 'ok': False}]
    monkeypatch.setattr(reportgen, 'coverage', coverage)
    ps = menu._sample_profiles_state(ctx)
    scr = ProfilesScreen(ctx, ps)
    vc = ps.vcatalog()
    ps.focus, ps.rcur = 'right', 0
    monkeypatch.setattr(ps, 'available', lambda _n: False)  # the cursor's component: no method here
    surf = BufferSurface(40, 160)
    vm = scr.render(surf, RecordingPalette(), ctx)
    assert vm.cur_oses_pending == vc[0]
    assert 'checking where it installs' in '\n'.join(surf.text_rows())
    deadline = time.time() + 5
    while ps.os_busy() and time.time() < deadline:
        if ps._os_done != ps._os_painted:
            break
        time.sleep(0.01)
    assert ps._os_done == 1
    vm = scr.render(surf, RecordingPalette(), ctx)
    assert vm.cur_oses == ['fedora'] and not vm.cur_oses_pending
    assert 'available on: fedora' in '\n'.join(surf.text_rows())
    assert not ps.os_busy()                                 # painted: the loop stops polling


# -- tui-core-19: the attrs vocabulary is one non-TUI table, and `check` flags a tag outside it -----

def test_unknown_attr_is_a_check_warning_and_the_shipped_catalog_has_none(tmp_path):
    from configsys import attrs, routecheck
    from configsys.routes import load
    from configsys.tui import modals
    assert modals._ATTR_AXIS_OF is attrs.ATTR_AXIS_OF          # the filter reads the same table
    routes = tmp_path / 'routes.hu'
    routes.write_text('{ os: { linux: {}  debian: { using: linux  native: apt } }  components: { '
                      't: { attrs: [ CLI GPL Foss ]  install: [ { via: native } ] } } }')
    casc, comps, drivers, _co = load(str(routes))
    iss = [i for i in routecheck.validate(comps, casc, drivers) if i.kind == 'unknown-attr']
    assert len(iss) == 1 and 'GPL' in iss[0].message and 'Foss' not in iss[0].message
    assert iss[0].severity == 'warning'
    casc, comps, drivers, _co = load(str(ROOT / 'routes.hu'))
    assert not [i for i in routecheck.validate(comps, casc, drivers) if i.kind == 'unknown-attr']


# -- tui-core-20: the `?` pages and the `!` overlay read the live keymap ----------------------------

def _rebound_keymap(**over):
    import copy
    from configsys.layers import read_tree
    from configsys.paths import Paths
    from configsys.tui.keyspec import Keymap
    _t, data = read_tree(Paths({}).config_file)
    keys = copy.deepcopy(data['keys'])
    for path, key in over.items():
        scope, action = path.split('__')
        keys[scope][action.replace('_', '-')] = key
    return Keymap(keys)


def test_every_help_key_reference_names_a_bound_action():
    from configsys.tui import help as tui_help
    from configsys.tui.keyspec import KNOWN_ACTIONS, shipped_keymap
    km = shipped_keymap()
    for screen, info in tui_help._HELP.items():
        text = info['desc'] + ' '.join(t + m for t, m in info.get('glossary', []))
        for scope, action in tui_help._KEY_REF.findall(text):
            assert action in KNOWN_ACTIONS.get(scope, set()) | KNOWN_ACTIONS['global'], (screen, scope, action)
            assert km.glyph(scope, action) != '?', (screen, scope, action)
        page = tui_help.help_page(screen, km)
        assert '{' not in page['desc'] + ''.join(t + m for t, m in page['glossary'])


def test_a_rebind_shows_on_the_help_page_and_the_issues_footer(monkeypatch):
    from configsys.tui import help as tui_help, modals
    km = _rebound_keymap(components__mode='Z', issues__report='Y')
    gloss = dict(tui_help.help_page('components', km)['glossary'])
    assert 'view (Z)' in gloss and 'view (M)' not in gloss
    monkeypatch.setattr(menu, '_KEYMAP', km)
    surf = BufferSurface(20, 140)
    modals._draw_diagnostics(surf, RecordingPalette(), [], 0)
    foot = surf.text_rows()[-1]
    assert 'Y report a component' in foot and 'r report' not in foot
    assert km.own_action('issues', ord('Y')) == 'report' and menu._ISSUE_KINDS['report'] == 'report'


# -- tui-core-22: the TUI's execute confirm answers like the CLI's (cli.common.ask) ----------------------------------

def _staged_ms():
    st = _state('fd', inst=None, latest='9')
    ms = MenuState({st.component.key: st}, [('user', ['fd'])])
    ms.staged[st.component.key] = 'install'
    return ms


class _Proceeded(Exception):
    pass


def _patch_execute(monkeypatch, answers):
    from configsys import actions
    from configsys.cli import refresh
    from configsys.tui import flows
    monkeypatch.setattr(flows, 'suspended', lambda _s: contextlib.nullcontext())
    monkeypatch.setattr(actions, 'build_plan', lambda c, raw, units, states=None: (raw, units, []))

    def past_the_question(*_a, **_k):
        raise _Proceeded
    monkeypatch.setattr(refresh, 'maybe_refresh_before_plan', past_the_question)
    asked = []

    def fake_input(prompt=''):
        asked.append(prompt)
        if not answers:
            raise EOFError
        return answers.pop(0)
    monkeypatch.setattr('builtins.input', fake_input)
    tty = types.SimpleNamespace(isatty=lambda: True)                # the TUI's own terminal
    monkeypatch.setattr('configsys.cli.common.sys', types.SimpleNamespace(stdin=tty, stdout=tty))
    return flows, asked


def test_execute_confirm_accepts_yes(monkeypatch):
    flows, asked = _patch_execute(monkeypatch, ['yes'])
    c = types.SimpleNamespace(runner=types.SimpleNamespace(pretend=False, sudo_session=contextlib.nullcontext))
    with pytest.raises(_Proceeded):
        flows._confirm_and_execute(None, None, _staged_ms(), c, None)
    assert asked and 'Proceed?' in asked[0]


def test_execute_confirm_under_pretend_does_not_ask(monkeypatch):
    flows, asked = _patch_execute(monkeypatch, [])
    c = types.SimpleNamespace(runner=types.SimpleNamespace(pretend=True, sudo_session=contextlib.nullcontext))
    with pytest.raises(_Proceeded):
        flows._confirm_and_execute(None, None, _staged_ms(), c, None)
    assert asked == []


def test_machines_current_first():
    from configsys.config import Config
    c = Config.__new__(Config)
    c.machine_names = lambda: ['alpha', 'box', 'zed']
    c.current_machine = lambda: 'box'
    assert Config.machines_current_first(c) == ['box', 'alpha', 'zed']
    c.current_machine = lambda: 'new'                      # no picks entry yet: still first
    assert Config.machines_current_first(c) == ['new', 'alpha', 'box', 'zed']


# -- tui-core-24: the provider picker tags the provider the resolver would pick ---------------------

def test_provider_picker_tags_the_highest_standing_provider_as_default(monkeypatch):
    from configsys.tui import flows
    comps = {'low': types.SimpleNamespace(never_auto=False, standing_rank=1, provides=['cap']),
             'high': types.SimpleNamespace(never_auto=False, standing_rank=5, provides=['cap']),
             'opt': types.SimpleNamespace(never_auto=True, standing_rank=0, provides=['cap'])}
    c = types.SimpleNamespace(routes=types.SimpleNamespace(components=comps, candidates=lambda p: [p]),
                              config=types.SimpleNamespace(pins=lambda: {}))
    seen = {}

    def chooser(_s, _p, _title, options, start=0, **_k):
        seen['options'], seen['start'] = dict(options), start
        return None
    monkeypatch.setattr(flows, '_popup_choose', chooser)
    flows._pick_provider_cap(None, None, c, 'low', 'cap', ['low', 'high', 'opt'])
    tags = seen['options']
    assert tags['high'] == 'current default' and 'default' not in tags['low'] and tags['opt'] == ''
    assert seen['start'] == 1                                 # the cursor starts on the one in effect
    comps['low'].standing_rank = 5                            # a tie: the resolver needs a pin, no default
    flows._pick_provider_cap(None, None, c, 'low', 'cap', ['low', 'high', 'opt'])
    assert not any('default' in t for t in seen['options'].values())


# -- tui-screens-15 / -16: the Config screen ---------------------------------------------------------

def test_config_unsynced_primary_is_not_where_edits_go(tmp_path):
    from configsys.tui.screens.config import ConfigScreen
    c = build_ctx(tmp_path)
    cfg = c.paths.user_config_file
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('{ plugins: [ { source: "github:nobody/x"  primary: true } ] }\n')
    c.invalidate()
    scr = ConfigScreen(c, menu.ConfigScreen(c))
    vm = scr.build_vm(c, (40, 160))
    assert vm.has_primary is False and '(primary not synced)' in vm.status
    for key, store in zip(vm.names, vm.stores):
        info = scr.model.settings[key]
        if info.get('nature') == 'uniform' and not str(info.get('source') or '').startswith('env '):
            assert store[2] != 'header', key                  # nothing reads as relocated


@pytest.mark.parametrize('key', ['disabled-drivers', 'primary-push'])
def test_config_cursor_block_taller_than_the_panel_still_paints(ctx, key):
    from configsys.tui.screens.config import ConfigScreen
    scr = ConfigScreen(ctx, menu.ConfigScreen(ctx))
    if key not in scr.model.keys:
        pytest.skip(f'{key} not in this catalog')
    scr.model.cur = scr.model.keys.index(key)
    surf = BufferSurface(12, 60)
    scr.render(surf, RecordingPalette(), ctx)
    body = surf.text_rows()[3:9]                           # the panel interior below its header row
    assert any(key[:10] in r for r in body)                # the block's columns row (name column) is painted…
    assert any(r.strip(' │█').startswith('…') for r in body)   # …and a cut-off marker after what fits


# -- tui-screens-21: notes and badges name the keys you bound ----------------------------------------

def test_system_update_note_and_plugins_empty_message_follow_a_rebind(ctx, monkeypatch):
    from configsys.tui.screens.components import ComponentsScreen
    from configsys.tui.screens.plugins import PluginsScreen
    km = _rebound_keymap(components__execute='Z', plugins__add='N')
    monkeypatch.setattr(menu, '_KEYMAP', km)
    st = _state('libc6', inst='1-1', latest='1-2', system_update=True)
    ms = MenuState({st.component.key: st}, [('System Updates', ['libc6'])])
    ms.toggle_expand_all()
    ms.cursor = ms.rows.index(next(n for n in ms.rows if n.kind == UNIT))
    monkeypatch.setattr('configsys.tui.screens.components._cursor_in_sysupd', lambda _m: True)
    monkeypatch.setattr(ms, 'stage_system_updates', lambda: 1)
    install = km.keys_for('components', 'op-install')[0]
    intent = ComponentsScreen(ctx, ms).handle(install, ctx, None, None, None, None)
    assert 'press Z to apply' in intent.note and 'press X' not in intent.note
    pl = menu._sample_plugins_state(ctx)
    pl.rows, pl.tree = [], []
    vm = PluginsScreen(ctx, pl).build_vm(ctx, (30, 120))
    assert vm.empty_msg == '(no plugins declared — N to add)'


# -- tui-screens-25 / -26: Profiles and Theme handling ---------------------------------------------

def test_comp_machines_closed_without_a_toggle_is_not_dirty(ctx, monkeypatch):
    from configsys.tui.screens import profiles as pmod
    ps = menu._sample_profiles_state(ctx)
    scr = pmod.ProfilesScreen(ctx, ps)
    ps.focus = 'right'
    monkeypatch.setattr(pmod, '_component_machines_modal', lambda *a, **k: '')
    reloads = []
    monkeypatch.setattr(ps, 'reload', lambda: reloads.append(1))
    key = menu._KEYMAP.keys_for('profiles', 'comp-machines')[0]
    intent = scr.handle(key, ctx, None, None)
    assert not intent.dirty and reloads == []


def test_track_with_no_target_machines_says_how_to_pick_some(ctx):
    from configsys.tui.screens.profiles import ProfilesScreen
    ps = menu._sample_profiles_state(ctx)
    ps.focus, ps.target_machines = 'right', set()
    key = menu._KEYMAP.keys_for('profiles', 'track-all')[0]
    intent = ProfilesScreen(ctx, ps).handle(key, ctx, None, None)
    g = menu._KEYMAP.glyph('profiles', 'machine-target')
    assert intent.note == f'no target machines — {g} to pick'


def test_theme_right_from_roles_stays_and_left_returns_to_the_map(ctx):
    from configsys.tui.screens.theme import ThemeScreen
    scr = ThemeScreen(ctx, menu.ThemeScreen(ctx), sample_ms=menu._sample_components_state())
    km = menu._KEYMAP
    right, left = km.keys_for('global', 'right')[0], km.keys_for('global', 'left')[0]
    scr.model.focus = 'roles'
    scr.handle(right, ctx, None, None)
    assert scr.model.focus == 'roles'                      # the right edge goes nowhere
    scr.handle(left, ctx, None, None)
    assert scr.model.focus == 'map'
    scr.model.map_ncols, scr.model.map_rows_per_col, scr.model.map_cur = 1, 10, 0
    scr.handle(left, ctx, None, None)
    assert scr.model.focus == 'map'                        # the left edge goes nowhere
    scr.handle(right, ctx, None, None)
    assert scr.model.focus == 'roles'
