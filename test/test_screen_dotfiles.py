'''Render-equivalence for the migrated Dotfiles screen (docs/d2-mvvm-plan.md): the new
DotfilesScreen.build_vm + draw must paint the IDENTICAL grid as the legacy _oracle._draw_dotfiles, so the
MVVM split is provably behavior-neutral. Both render the same _sample_dotfiles_state into a
BufferSurface under the same RecordingPalette. Plus a few handle() behaviour checks.'''

import pytest

from _render_harness import RecordingPalette, build_ctx
from configsys.tui import menu
import _legacy_render as _oracle
from configsys.tui.screens.dotfiles import DotfilesScreen
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
    return build_ctx(tmp_path_factory.mktemp('dotf'))


def _both(ctx, h, w, mode, cur=0, hscroll=0):
    legacy = menu._sample_dotfiles_state(ctx)
    fresh = menu._sample_dotfiles_state(ctx)
    legacy.cur = fresh.cur = cur
    legacy.hscroll = fresh.hscroll = hscroll
    sL, sN = BufferSurface(h, w), BufferSurface(h, w)
    _oracle._draw_dotfiles(sL, _pal(mode), legacy, ctx, '', 'dotfiles')
    scr = DotfilesScreen(ctx, fresh)
    scr.draw(sN, _pal(mode), scr.build_vm(ctx, (h, w)))
    return sL.grid(), sN.grid()


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('h,w', SIZES, ids=['roomy', 'tight', 'mid'])
def test_dotfiles_equivalent(ctx, h, w, mode):
    legacy, new = _both(ctx, h, w, mode)
    assert new == legacy


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('h,w', SIZES, ids=['roomy', 'tight', 'mid'])
def test_dotfiles_scrolled_equivalent(ctx, h, w, mode):
    # cursor off row 0 + a horizontal offset (over-large, so the clamp path is exercised too)
    legacy, new = _both(ctx, h, w, mode, cur=2, hscroll=400)
    assert new == legacy


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('h,w', SIZES, ids=['roomy', 'tight', 'mid'])
def test_dotfiles_empty_equivalent(ctx, h, w, mode):
    legacy = menu._sample_dotfiles_state(ctx)
    fresh = menu._sample_dotfiles_state(ctx)
    legacy.rows, legacy.display = [], []
    fresh.rows, fresh.display = [], []
    sL, sN = BufferSurface(h, w), BufferSurface(h, w)
    _oracle._draw_dotfiles(sL, _pal(mode), legacy, ctx, '', 'dotfiles')
    scr = DotfilesScreen(ctx, fresh)
    scr.draw(sN, _pal(mode), scr.build_vm(ctx, (h, w)))
    assert sN.grid() == sL.grid()


def test_dotfiles_build_vm_is_pure_data(ctx):
    scr = DotfilesScreen(ctx, menu._sample_dotfiles_state(ctx))
    vm = scr.build_vm(ctx, (40, 200))
    assert vm.has_rows and vm.cells and len(vm.cells[0]) == len(vm.headers)
    assert len(vm.elems) == len(vm.cells) == len(vm.display) == 4
    assert vm.elems == ['installed', 'outdated', 'info_dim', 'installed']   # managed/unmanaged/no config/managed
    assert vm.widths and vm.xs[0] == 0 and vm.virt_w == sum(vm.widths) + 2 * (len(vm.widths) - 1)
    assert '4 config target(s)' in vm.status
    assert '2 managed' in vm.status and '1 unmanaged' in vm.status and '1 no config' in vm.status
    assert '! 1 unmanaged file(s) at risk' in vm.status
    assert vm.nav


# -- handle() behaviour ---------------------------------------------------

def test_handle_nav_moves_cursor_and_scrolls(ctx):
    scr = DotfilesScreen(ctx, menu._sample_dotfiles_state(ctx))
    scr.model.cur = 0
    km = menu._KEYMAP
    down = next(k for k in range(32, 127) if km.action_for('dotfiles', k) == 'down')
    right = next(k for k in range(32, 127) if km.action_for('dotfiles', k) == 'right')
    intent = scr.handle(down, ctx, None, None)
    assert scr.model.cur == 1
    assert intent.handled and not intent.dirty and intent.note is None
    scr.handle(right, ctx, None, None)
    assert scr.model.hscroll == 4
    assert scr.model.dirty == set()                       # pure nav touches no unit


def test_handle_move_store_all_without_primary_plugin_notes(ctx):
    scr = DotfilesScreen(ctx, menu._sample_dotfiles_state(ctx))
    assert ctx.paths.primary_dotfiles_dir is None         # the harness ctx has no primary plugin
    km = menu._KEYMAP
    key = next(k for k in range(32, 127) if km.action_for('dotfiles', k) == 'move-store-all')
    intent = scr.handle(key, ctx, None, None)
    assert intent.note == 'no primary plugin configured — nothing to move between'
    assert scr.model.dirty == set()


def test_dotfiles_note_renders_in_status(ctx):
    # the router supplies vm.note; draw must render it (a class of bug the note='' equivalence
    # cases can't catch — the legacy painters append it to the status line).
    scr = DotfilesScreen(ctx, menu._sample_dotfiles_state(ctx))
    vm = scr.build_vm(ctx, (40, 200))
    vm.note = 'ZZ_NOTE_MARKER_ZZ'
    surf = BufferSurface(40, 200)
    scr.draw(surf, RecordingPalette(), vm)
    assert 'ZZ_NOTE_MARKER_ZZ' in ' '.join(surf.text_rows())
