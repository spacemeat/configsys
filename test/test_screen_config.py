'''Render-equivalence for the migrated Config screen (docs/d2-mvvm-plan.md): the new
ConfigScreen.build_vm + draw must paint the IDENTICAL grid as the legacy _oracle._draw_config, so the
MVVM split is provably behavior-neutral. Both render a fresh menu.ConfigScreen(ctx) (the settings
catalog is deterministic for a fixed ctx) into a BufferSurface under the same RecordingPalette. Plus
a few handle() behaviour checks.'''

import pytest

from _render_harness import RecordingPalette, build_ctx
from configsys.tui import menu
import _legacy_render as _oracle
from configsys.tui.screens.base import Intent
from configsys.tui.screens.config import ConfigScreen
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
    return build_ctx(tmp_path_factory.mktemp('conf'))


def _both(ctx, h, w, mode, cur=0):
    legacy = menu.ConfigScreen(ctx)
    fresh = menu.ConfigScreen(ctx)
    legacy.cur = fresh.cur = cur
    sL, sN = BufferSurface(h, w), BufferSurface(h, w)
    _oracle._draw_config(sL, _pal(mode), legacy, ctx, '', 'config')
    scr = ConfigScreen(ctx, fresh)
    scr.draw(sN, _pal(mode), scr.build_vm(ctx, (h, w)))
    return sL.grid(), sN.grid()


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('h,w', SIZES, ids=['roomy', 'tight', 'mid'])
def test_config_top_equivalent(ctx, h, w, mode):
    legacy, new = _both(ctx, h, w, mode, cur=0)
    assert new == legacy


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('h,w', SIZES, ids=['roomy', 'tight', 'mid'])
def test_config_scrolled_equivalent(ctx, h, w, mode):
    n = len(menu.ConfigScreen(ctx).keys)
    legacy, new = _both(ctx, h, w, mode, cur=max(0, n - 1))   # forces the keep-cursor scroll
    assert new == legacy


def test_config_build_vm_is_pure_data(ctx):
    scr = ConfigScreen(ctx, menu.ConfigScreen(ctx))
    vm = scr.build_vm(ctx, (40, 200))
    n = len(scr.model.keys)
    assert n and len(vm.names) == len(vm.values) == len(vm.states) == len(vm.stores) == n
    assert len(vm.descs) == len(vm.mans) == n
    assert all(isinstance(d, list) and d for d in vm.descs)
    assert all(len(s) == 2 for s in vm.states) and all(len(s) == 3 for s in vm.stores)
    assert all(m.startswith('man: ') for m in vm.mans)
    assert 'edits →' in vm.status and vm.nav
    assert scr.model.top == 0 and scr.model.cur == 0     # build_vm never scrolls the model


# -- handle() behaviour ---------------------------------------------------

def test_handle_nav_moves_cursor(ctx):
    scr = ConfigScreen(ctx, menu.ConfigScreen(ctx))
    scr.model.cur = 0
    km = menu._KEYMAP
    down = next(k for k in range(32, 127) if km.action_for('config', k) == 'down')
    intent = scr.handle(down, ctx, None, None)
    assert scr.model.cur == 1
    assert intent.handled and not intent.dirty and intent.goto is None


def test_handle_theme_jumps_to_theme_screen(ctx):
    scr = ConfigScreen(ctx, menu.ConfigScreen(ctx))
    km = menu._KEYMAP
    theme = next(k for k in range(32, 127) if km.action_for('config', k) == 'theme')
    intent = scr.handle(theme, ctx, None, None)
    assert isinstance(intent, Intent)
    assert intent.goto == 'theme'
    assert intent.handled and not intent.dirty and intent.note is None


def test_config_note_renders_in_status(ctx):
    # the router supplies vm.note; draw must render it (a class of bug the note='' equivalence
    # cases can't catch — the legacy painters append it to the status line).
    scr = ConfigScreen(ctx, menu.ConfigScreen(ctx))
    vm = scr.build_vm(ctx, (40, 200))
    vm.note = 'ZZ_NOTE_MARKER_ZZ'
    surf = BufferSurface(40, 200)
    scr.draw(surf, RecordingPalette(), vm)
    assert 'ZZ_NOTE_MARKER_ZZ' in ' '.join(surf.text_rows())
