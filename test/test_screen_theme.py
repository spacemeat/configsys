'''Render-equivalence for the migrated Theme screen (docs/d2-mvvm-plan.md): the new
ThemeScreen.build_vm + draw must paint the IDENTICAL grid as the legacy _oracle._draw_theme (the
top-level, sample=True render — the self-preview sub-page stays legacy), so the MVVM split is
provably behavior-neutral. Both render a fresh menu.ThemeScreen model over the same live ctx into a
BufferSurface under the same RecordingPalette, across sizes × color modes × focus/page states. Plus a
build_vm purity check and a few handle() navigation checks (no color-EDIT branches — those need
stdin via _input_box).'''

import pytest

from _render_harness import RecordingPalette, build_ctx
from configsys.tui import menu
import _legacy_render as _oracle
from configsys.tui.screens.theme import ThemeScreen
from configsys.tui.surface import BufferSurface

SIZES = [(40, 120), (24, 80), (30, 100)]
MODES = ['grad', 'flat', 'lowcolor', 'mono']
# (focus, page index into ALL_PAGES): map on components; roles on components; the F2 profiles page;
# roles on the config page; and the editor previewing itself (F7)
STATES = [('map', 0), ('roles', 0), ('map', 1), ('roles', 5), ('roles', 6)]


def _pal(mode):
    return {
        'grad': RecordingPalette(gradient=True, have256=True),
        'flat': RecordingPalette(gradient=False, have256=True),
        'lowcolor': RecordingPalette(gradient=False, have256=False),
        'mono': RecordingPalette(gradient=False, have256=False, mono=True),
    }[mode]


@pytest.fixture(scope='module')
def ctx(tmp_path_factory):
    return build_ctx(tmp_path_factory.mktemp('theme'))


def _model(ctx, focus, page):
    ts = menu.ThemeScreen(ctx)
    ts.focus, ts.page = focus, page
    ts.map_cur, ts.role_cur = 2, 1                        # off the origin so selection rows differ
    return ts


def _both(ctx, h, w, mode, focus='map', page=0):
    legacy = _model(ctx, focus, page)                     # TWO fresh models: draw mutates
    fresh = _model(ctx, focus, page)                      # map_top/role_top/map_ncols
    sample_ms = menu._sample_components_state()
    sL, sN = BufferSurface(h, w), BufferSurface(h, w)
    _oracle._draw_theme(sL, _pal(mode), legacy, ctx, '', 'theme', sample_ms, True)
    scr = ThemeScreen(ctx, fresh, sample_ms)
    scr.draw(sN, _pal(mode), scr.build_vm(ctx, (h, w)))
    return sL.grid(), sN.grid()


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('h,w', SIZES, ids=['roomy', 'tight', 'mid'])
@pytest.mark.parametrize('focus,page', STATES, ids=[f'{f}-p{p}' for f, p in STATES])
def test_theme_equivalent(ctx, h, w, mode, focus, page):
    legacy, new = _both(ctx, h, w, mode, focus=focus, page=page)
    assert new == legacy


def test_theme_build_vm_is_pure_data(ctx):
    scr = ThemeScreen(ctx, _model(ctx, 'roles', 0), menu._sample_components_state())
    vm = scr.build_vm(ctx, (40, 120))
    assert vm.page == 'components' and vm.focus == 'roles'
    assert vm.map_rows and all(len(r) == 3 for r in vm.map_rows)
    assert len(vm.map_rows) == len(scr.model.map_names)
    assert len(vm.role_rows) == len(scr.model.role_list())
    kinds = [r[0] for r in vm.role_rows]
    assert kinds.count('grad') == 2 and 'role' in kinds     # the two endpoints ride the role list
    assert vm.edit_target


# -- handle() behaviour ---------------------------------------------------

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
