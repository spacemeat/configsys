'''Render-regression for the Components screen (docs/d2-mvvm-plan.md), post-oracle style. The model
is a MenuState; `_sample_components_state()` is a HAND-BUILT synthetic tree (no routes.hu), so it IS
the fake data — the draw assertions read stable, sample-defined content. build_vm is a thin pass of
the frame inputs (note + diagnostics). Plus handle() behaviour.'''

import pytest

from _render_harness import RecordingPalette, build_ctx
from configsys.tui import menu
from configsys.tui.screens.components import ComponentsScreen, ComponentsVM
from configsys.tui.surface import BufferSurface

DIAGS = [{'level': 'warn', 'tag': 'sample', 'text': 'an example issue'}]


@pytest.fixture(scope='module')
def ctx(tmp_path_factory):
    return build_ctx(tmp_path_factory.mktemp('comp'))


# -- build_vm: the frame inputs pass through to the ViewModel ------------------

def test_build_vm_carries_note_and_diags():
    scr = ComponentsScreen.__new__(ComponentsScreen)
    scr.note, scr.diags = 'hello', tuple(DIAGS)
    vm = scr.build_vm(None, (40, 120))
    assert isinstance(vm, ComponentsVM)
    assert vm.note == 'hello' and vm.diags == tuple(DIAGS)


# -- draw: the tree/header/legend paint from the hand-built sample -------------

def _draw(ctx, note='', diags=(), h=40, w=120):
    scr = ComponentsScreen(ctx, menu._sample_components_state())
    scr.note, scr.diags = note, diags
    surf = BufferSurface(h, w)
    scr.draw(surf, RecordingPalette(), scr.build_vm(ctx, (h, w)))
    return surf


def test_draw_header_columns_rows_and_footers(ctx):
    surf = _draw(ctx)
    rows = surf.text_rows()
    joined = '\n'.join(rows)
    assert rows[1].startswith(' configsys ')                 # the chip on the title line
    assert 'view: to-do' in rows[1]                          # the MODE indicator
    for col in ('component', 'driver', 'scope', 'status', 'installed', 'latest'):
        assert col in rows[2]                                # the column header row
    assert 'ripgrep' in joined and 'bottom' in joined        # sample components render as tree rows
    assert 'selected:0' in joined and 'staged:' in joined    # the status line
    assert 'exec' in rows[-1] and 'issues' in rows[-1]       # the action legend footer


def test_draw_shows_note_and_issue_badge(ctx):
    surf = _draw(ctx, note='ZZ_NOTE_ZZ', diags=tuple(DIAGS))
    joined = '\n'.join(surf.text_rows())
    assert 'ZZ_NOTE_ZZ' in joined                            # the transient note on the status line
    assert 'issue' in surf.text_rows()[1]                    # the ⚠ N issue attention badge


def test_draw_no_badge_without_diags(ctx):
    surf = _draw(ctx, diags=())
    assert 'issue' not in surf.text_rows()[1]                # no diagnostics -> no badge


# -- handle() behaviour -------------------------------------------------------

def test_handle_down_moves_cursor(ctx):
    scr = ComponentsScreen(ctx, menu._sample_components_state())
    scr.model.cursor = 0
    km = menu._KEYMAP
    down = next(k for k in range(32, 127) if km.action_for('components', k) == 'down')
    intent = scr.handle(down, ctx, None, None, None, None)
    assert scr.model.cursor == 1
    assert intent.reloaded is None and intent.remodeled is None


def test_handle_lock_on_profile_row_is_a_noop(ctx):
    scr = ComponentsScreen(ctx, menu._sample_components_state())
    scr.model.go_top()                                       # a profile row -> nothing lockable
    km = menu._KEYMAP
    lock = next((k for k in range(32, 127) if km.action_for('components', k) == 'lock'), None)
    if lock is None:
        pytest.skip('no lock binding')
    intent = scr.handle(lock, ctx, None, None, None, None)
    assert intent.reloaded is None                            # no reprobe, no crash


def test_footer_lock_verb_flips_to_unlock_when_target_locked(ctx):
    # the toggle key is one key both ways; the footer names the direction it will go, so a locked
    # (or lock-staged) row shows `L unlock` instead of the invisible-other-half `L lock`.
    from configsys.tui.screens.components import _lock_verb
    scr = ComponentsScreen(ctx, menu._sample_components_state())
    ms = scr.model
    ms.clear_all_staged()                                    # deterministic: nothing staged anywhere
    ms.selected.clear()
    for i in range(len(ms.rows)):                            # park on a truly-unlocked lockable row
        ms.cursor = i
        if _lock_verb(ms) == 'lock' and ms.toggle_lock():    # verb was "lock" -> this stages a lock
            break
    else:
        pytest.skip('sample has no lockable unlocked row')
    assert 'L unlock' in _rows(scr, ctx)[-1]                 # a lock is staged -> the toggle now UNLOCKS
    ms.clear_all_staged()
    assert 'L lock' in _rows(scr, ctx)[-1]                   # cleared -> back to "lock" on the same row


def _rows(scr, ctx):
    surf = BufferSurface(40, 120)
    scr.draw(surf, RecordingPalette(), scr.build_vm(ctx, (40, 120)))
    return surf.text_rows()
