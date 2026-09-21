'''Render-equivalence for the migrated Plugins screen (docs/d2-mvvm-plan.md): the new
PluginsScreen.build_vm + draw must paint the IDENTICAL grid as the legacy menu._draw_plugins, so the
MVVM split is provably behavior-neutral. Both render the same _sample_plugins_state into a
BufferSurface under the same RecordingPalette. Plus a few handle() behaviour checks.'''

import pytest

from _render_harness import RecordingPalette, build_ctx
from configsys.tui import menu
from configsys.tui.screens.plugins import PluginsScreen
from configsys.tui.surface import BufferSurface

SIZES = [(40, 120), (24, 80), (30, 100)]
MODES = ['grad', 'flat', 'lowcolor', 'mono']


def _pal(mode):
    return {
        'grad': RecordingPalette(gradient=True, have256=True),
        'flat': RecordingPalette(gradient=False, have256=True),
        'lowcolor': RecordingPalette(gradient=False, have256=False),
        'mono': RecordingPalette(gradient=False, have256=False, mono=True),
    }[mode]


@pytest.fixture(scope='module')
def ctx(tmp_path_factory):
    return build_ctx(tmp_path_factory.mktemp('plug'))


def _both(ctx, h, w, mode, focus='table'):
    legacy = menu._sample_plugins_state(ctx)
    fresh = menu._sample_plugins_state(ctx)
    legacy.focus = fresh.focus = focus
    sL, sN = BufferSurface(h, w), BufferSurface(h, w)
    menu._draw_plugins(sL, _pal(mode), legacy, ctx, '', 'plugins')
    scr = PluginsScreen(ctx, fresh)
    scr.draw(sN, _pal(mode), scr.build_vm(ctx, (h, w)))
    return sL.grid(), sN.grid()


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('h,w', SIZES, ids=['roomy', 'tight', 'mid'])
def test_plugins_table_focus_equivalent(ctx, h, w, mode):
    legacy, new = _both(ctx, h, w, mode, focus='table')
    assert new == legacy


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('h,w', SIZES, ids=['roomy', 'tight', 'mid'])
def test_plugins_diff_focus_equivalent(ctx, h, w, mode):
    legacy, new = _both(ctx, h, w, mode, focus='diff')
    assert new == legacy


def test_plugins_build_vm_is_pure_data(ctx):
    scr = PluginsScreen(ctx, menu._sample_plugins_state(ctx))
    vm = scr.build_vm(ctx, (40, 200))
    assert vm.has_rows and vm.cells and len(vm.cells[0]) == len(vm.headers)
    assert vm.diff_has_files and vm.diff_lines            # the sample has a mocked diff
    assert 'plugin(s)' in vm.status and vm.nav


# -- handle() behaviour ---------------------------------------------------

def test_handle_nav_moves_cursor_and_invalidates_diff(ctx):
    scr = PluginsScreen(ctx, menu._sample_plugins_state(ctx))
    scr.model.cur = 0
    scr.model.diff_key = ('x', 'y', 'z')                  # pretend a diff is loaded
    km = menu._KEYMAP
    down = next(k for k in range(32, 127) if km.action_for('plugins', k) == 'down')
    intent = scr.handle(down, ctx, None, None)
    assert scr.model.cur == 1
    assert scr.model.diff_key is None                     # nav invalidates the loaded diff
    assert intent.handled and not intent.dirty


def test_handle_switch_pane_toggles_focus(ctx):
    scr = PluginsScreen(ctx, menu._sample_plugins_state(ctx))
    scr.model.focus = 'table'
    km = menu._KEYMAP
    tab = next(k for k in range(1, 400) if km.action_for('plugins', k) == 'switch-pane')
    scr.handle(tab, ctx, None, None)
    assert scr.model.focus == 'diff'


def test_plugins_note_renders_in_status(ctx):
    # the router supplies vm.note; draw must render it (a class of bug the note='' equivalence
    # cases can't catch — the legacy painters append it to the status line).
    scr = PluginsScreen(ctx, menu._sample_plugins_state(ctx))
    vm = scr.build_vm(ctx, (40, 200))
    vm.note = 'ZZ_NOTE_MARKER_ZZ'
    surf = BufferSurface(40, 200)
    scr.draw(surf, RecordingPalette(), vm)
    assert 'ZZ_NOTE_MARKER_ZZ' in ' '.join(surf.text_rows())
