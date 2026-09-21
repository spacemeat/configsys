'''Render-regression for the Theme screen (docs/d2-mvvm-plan.md), post-oracle style. build_vm runs on
the REAL (deterministic) theme model; draw is pinned against a HAND-BUILT ThemeVM (with the inner
sample slot suppressed, so no ctx/sub-screens are needed). Plus handle() navigation.'''

from types import SimpleNamespace

import pytest

from _render_harness import RecordingPalette, build_ctx
from configsys.tui import menu
from configsys.tui.screens.theme import ThemeScreen, ThemeVM
from configsys.tui.surface import BufferSurface


@pytest.fixture(scope='module')
def ctx(tmp_path_factory):
    return build_ctx(tmp_path_factory.mktemp('theme'))


def _model(ctx, focus='roles', page=0):
    ts = menu.ThemeScreen(ctx)
    ts.focus, ts.page = focus, page
    ts.map_cur, ts.role_cur = 2, 1
    return ts


# -- build_vm: the two lists' content from the real (stable) theme model -------

def test_build_vm_map_and_role_rows(ctx):
    scr = ThemeScreen(ctx, _model(ctx, 'roles', 0), menu._sample_components_state())
    vm = scr.build_vm(ctx, (40, 120))
    assert vm.page == 'components' and vm.focus == 'roles'
    assert vm.map_rows and all(len(r) == 3 for r in vm.map_rows)      # (name, rgb, override-mark)
    assert len(vm.map_rows) == len(scr.model.map_names)
    assert len(vm.role_rows) == len(scr.model.role_list())
    kinds = [r[0] for r in vm.role_rows]
    assert kinds.count('grad') == 2 and 'role' in kinds              # the two gradient endpoints ride
    assert vm.edit_target


# -- draw: a HAND-BUILT ViewModel paints the two panels + chrome ---------------

def test_draw_panels_status_and_note():
    vm = ThemeVM()
    vm.page = 'components'
    vm.focus = 'map'
    vm.map_rows = [('accent', (200, 140, 240), '*'), ('dim', (100, 100, 100), ' ')]
    vm.role_rows = [('grad', (10, 20, 30), 'gradient from  #0a141e'),
                    ('role', (235, 235, 235), None,
                     {'bold': True, 'underline': False, 'reverse': False}, 'component     fg/bg  b')]
    vm.edit_target = 'your primary'
    vm.note = 'accent = #c88cf0'

    scr = ThemeScreen.__new__(ThemeScreen)
    scr.ctx = None                                    # unused: the sample slot is suppressed
    scr.sample_ms = None
    scr.suppress_sample = True
    scr.model = SimpleNamespace(focus='map', map_cur=0, map_top=0, role_cur=0, role_top=0,
                                map_ncols=1, map_rows_per_col=100)

    surf = BufferSurface(30, 120)
    scr.draw(surf, RecordingPalette(), vm)
    joined = '\n'.join(surf.text_rows())
    assert 'color map (shared)' in joined                 # the map panel title
    assert 'page roles — components' in joined            # the roles panel title (carries the page)
    assert 'accent' in joined and '#c88cf0' in joined     # a map row: name + hex
    assert '· live sample ·' in joined                    # the suppressed-sample placeholder
    assert 'terminal color: harness' in joined            # status (RecordingPalette.color_mode)
    assert 'edits → your primary' in joined
    assert 'accent = #c88cf0' in joined                   # the appended note
    assert surf.text_rows()[-1].strip()                   # a nav footer row is painted


# -- handle() behaviour -------------------------------------------------------

def test_handle_switch_pane_toggles_focus(ctx):
    scr = ThemeScreen(ctx, _model(ctx, 'map', 0))
    km = menu._KEYMAP
    tab = next(k for k in range(1, 400) if km.action_for('theme', k) == 'switch-pane')
    intent = scr.handle(tab, ctx, None, None)
    assert scr.model.focus == 'roles'
    assert intent.handled and intent.new_pal is None and not intent.dirty and intent.goto is None
    scr.handle(tab, ctx, None, None)
    assert scr.model.focus == 'map'


def test_handle_down_moves_focused_cursor(ctx):
    scr = ThemeScreen(ctx, _model(ctx, 'map', 0))
    scr.model.map_cur = scr.model.role_cur = 0
    km = menu._KEYMAP
    down = next(k for k in range(32, 127) if km.action_for('theme', k) == 'down')
    scr.handle(down, ctx, None, None)
    assert (scr.model.map_cur, scr.model.role_cur) == (1, 0)
    scr.model.focus = 'roles'
    scr.handle(down, ctx, None, None)
    assert (scr.model.map_cur, scr.model.role_cur) == (1, 1)


def test_handle_page_key_switches_sample_page(ctx):
    scr = ThemeScreen(ctx, _model(ctx, 'map', 0))
    km = menu._KEYMAP
    f2 = next(k for k in range(1, 600) if km.action_for('theme', k) == 'page-2')
    scr.handle(f2, ctx, None, None)
    assert scr.model.page == 1 and scr.model.page_name() == 'profiles'
