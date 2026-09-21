'''Render-equivalence for the migrated Glue screen (docs/d2-mvvm-plan.md): the new
GlueScreen.build_vm + draw must paint the IDENTICAL grid as the legacy menu._draw_glue, so the MVVM
split is provably behavior-neutral. Both render the same _sample_glue_state into a BufferSurface
under the same RecordingPalette. Plus a few handle() behaviour checks.'''

import pytest

from _render_harness import RecordingPalette, build_ctx
from configsys.tui import menu
from configsys.tui.screens.glue import GlueScreen
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
    return build_ctx(tmp_path_factory.mktemp('glue'))


def _both(ctx, h, w, mode, cur=0, hscroll=0, empty=False):
    # two FRESH samples — draw clamps hscroll/top back onto the model it paints
    legacy = menu._sample_glue_state(ctx)
    fresh = menu._sample_glue_state(ctx)
    for gs in (legacy, fresh):
        gs.cur, gs.hscroll = cur, hscroll
        if empty:
            gs.rows, gs.display, gs.loader = [], [], {}
    sL, sN = BufferSurface(h, w), BufferSurface(h, w)
    menu._draw_glue(sL, _pal(mode), legacy, ctx, '', 'glue')
    scr = GlueScreen(ctx, fresh)
    scr.draw(sN, _pal(mode), scr.build_vm(ctx, (h, w)))
    return sL.grid(), sN.grid()


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('h,w', SIZES, ids=['roomy', 'tight', 'mid'])
def test_glue_equivalent(ctx, h, w, mode):
    legacy, new = _both(ctx, h, w, mode)
    assert new == legacy


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('h,w', SIZES, ids=['roomy', 'tight', 'mid'])
def test_glue_cursor_in_second_group_equivalent(ctx, h, w, mode):
    legacy, new = _both(ctx, h, w, mode, cur=3)             # the fish row, past the fish header
    assert new == legacy


@pytest.mark.parametrize('mode', MODES)
def test_glue_hscroll_narrow_equivalent(ctx, mode):
    # a panel narrower than the virtual table width -> the has_hbar / rows_h branch + a clamped hscroll
    legacy, new = _both(ctx, 12, 50, mode, cur=2, hscroll=200)
    assert new == legacy


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('h,w', SIZES, ids=['roomy', 'tight', 'mid'])
def test_glue_empty_equivalent(ctx, h, w, mode):
    legacy, new = _both(ctx, h, w, mode, empty=True)
    assert new == legacy


def test_glue_build_vm_is_pure_data(ctx):
    scr = GlueScreen(ctx, menu._sample_glue_state(ctx))
    vm = scr.build_vm(ctx, (40, 200))
    assert vm.has_rows and vm.cells and len(vm.cells[0]) == len(vm.headers)
    assert len(vm.elems) == len(vm.cells) == len(scr.model.rows)
    assert [e[0] for e in vm.display] == ['hdr', 'row', 'row', 'row', 'hdr', 'row']
    assert vm.display[0][1].startswith('bash  loader: ')
    assert vm.cur_disp == 1                                # cursor row 0 sits after the bash header
    assert 'glue snippet(s)' in vm.status and 'changed' in vm.status and vm.nav
    # the model's scroll fields are untouched by build_vm (draw owns the clamps)
    assert scr.model.top == 0 and scr.model.hscroll == 0


# -- handle() behaviour ---------------------------------------------------

def test_handle_nav_moves_cursor(ctx):
    scr = GlueScreen(ctx, menu._sample_glue_state(ctx))
    scr.model.cur = 0
    km = menu._KEYMAP
    down = next(k for k in range(32, 127) if km.action_for('glue', k) == 'down')
    intent = scr.handle(down, ctx, None, None)
    assert scr.model.cur == 1
    assert intent.handled and intent.note is None and not scr.model.dirty
    bottom = next(k for k in range(32, 127) if km.action_for('glue', k) == 'bottom')
    scr.handle(bottom, ctx, None, None)
    assert scr.model.cur == len(scr.model.rows) - 1


def test_handle_right_left_scrolls(ctx):
    scr = GlueScreen(ctx, menu._sample_glue_state(ctx))
    km = menu._KEYMAP
    right = next(k for k in range(32, 127) if km.action_for('glue', k) == 'right')
    left = next(k for k in range(32, 127) if km.action_for('glue', k) == 'left')
    scr.handle(right, ctx, None, None)
    assert scr.model.hscroll == 4
    scr.handle(left, ctx, None, None)
    scr.handle(left, ctx, None, None)
    assert scr.model.hscroll == 0                          # clamped at 0


def test_glue_note_renders_in_status(ctx):
    # the router supplies vm.note; draw must render it (a class of bug the note='' equivalence
    # cases can't catch — the legacy painters append it to the status line).
    scr = GlueScreen(ctx, menu._sample_glue_state(ctx))
    vm = scr.build_vm(ctx, (40, 200))
    vm.note = 'ZZ_NOTE_MARKER_ZZ'
    surf = BufferSurface(40, 200)
    scr.draw(surf, RecordingPalette(), vm)
    assert 'ZZ_NOTE_MARKER_ZZ' in ' '.join(surf.text_rows())
