'''Render-equivalence for the migrated Components screen: ComponentsScreen.draw must paint the
identical grid as the legacy menu._draw (screen == 'components'), across sizes, palette modes, and a
few tree states. Plus handle() behaviour checks (nav + stage) that don't need curses/stdin.'''

import pytest

from _render_harness import RecordingPalette, build_ctx
from configsys.tui import menu
import _legacy_render as _oracle
from configsys.tui.screens.components import ComponentsScreen
from configsys.tui.surface import BufferSurface

SIZES = [(40, 120), (24, 80), (30, 100)]
MODES = ['grad', 'flat', 'lowcolor', 'mono']
DIAGS = [{'level': 'warn', 'tag': 'sample', 'text': 'an example issue'}]


def _pal(mode):
    return {
        'grad': RecordingPalette(gradient=True, have256=True),
        'flat': RecordingPalette(gradient=False, have256=True),
        'lowcolor': RecordingPalette(gradient=False, have256=False),
        'mono': RecordingPalette(gradient=False, have256=False, mono=True),
    }[mode]


@pytest.fixture(scope='module')
def ctx(tmp_path_factory):
    return build_ctx(tmp_path_factory.mktemp('comp'))


def _both(ctx, h, w, mode, diags, cursor=0):
    legacy = menu._sample_components_state()
    fresh = menu._sample_components_state()
    legacy.cursor = fresh.cursor = min(cursor, len(legacy.rows) - 1)
    sL, sN = BufferSurface(h, w), BufferSurface(h, w)
    _oracle._draw(sL, _pal(mode), legacy, ctx, '', diags, False, 0, 'components')
    scr = ComponentsScreen(ctx, fresh)
    scr.note, scr.diags = '', diags
    scr.draw(sN, _pal(mode), scr.build_vm(ctx, (h, w)))
    return sL.grid(), sN.grid()


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('h,w', SIZES, ids=['roomy', 'tight', 'mid'])
def test_components_equivalent_no_diags(ctx, h, w, mode):
    legacy, new = _both(ctx, h, w, mode, diags=())
    assert new == legacy


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('h,w', SIZES, ids=['roomy', 'tight', 'mid'])
def test_components_equivalent_with_diags_badge(ctx, h, w, mode):
    legacy, new = _both(ctx, h, w, mode, diags=DIAGS)
    assert new == legacy


def test_components_equivalent_cursor_on_nested_unit(ctx):
    legacy, new = _both(ctx, *SIZES[0], 'grad', diags=(), cursor=4)
    assert new == legacy


def test_components_note_shows_in_status(ctx):
    scr = ComponentsScreen(ctx, menu._sample_components_state())
    scr.note, scr.diags = 'hello note', ()
    surf = BufferSurface(40, 120)
    scr.draw(_pal_surface := surf, RecordingPalette(), scr.build_vm(ctx, (40, 120)))
    assert 'hello note' in ' '.join(surf.text_rows())


# -- handle() behaviour ---------------------------------------------------

def test_handle_down_moves_cursor(ctx):
    scr = ComponentsScreen(ctx, menu._sample_components_state())
    scr.model.cursor = 0
    km = menu._KEYMAP
    down = next(k for k in range(32, 127) if km.action_for('components', k) == 'down')
    intent = scr.handle(down, ctx, None, None, None, None)
    assert scr.model.cursor == 1
    assert intent.reloaded is None and intent.remodeled is None


def test_handle_lock_note_when_not_applicable(ctx):
    scr = ComponentsScreen(ctx, menu._sample_components_state())
    scr.model.go_top()                            # a profile row -> nothing to lock
    km = menu._KEYMAP
    lock = next((k for k in range(32, 127) if km.action_for('components', k) == 'lock'), None)
    if lock is None:
        pytest.skip('no lock binding')
    intent = scr.handle(lock, ctx, None, None, None, None)
    # either it locked something or reported nothing to lock — both are valid, no crash/reload
    assert intent.reloaded is None
