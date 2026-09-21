'''Render-equivalence for the migrated Profiles screen (docs/d2-mvvm-plan.md): the new
ProfilesScreen.build_vm + draw must paint the IDENTICAL grid as the legacy menu._draw_profiles, so
the MVVM split is provably behavior-neutral. Both render a fresh _sample_profiles_state (whose .ctx
is the deterministic sample overlay) into a BufferSurface under the same RecordingPalette, for both
pane focuses. Plus a few handle() behaviour checks.'''

import pytest

from _render_harness import RecordingPalette, build_ctx
from configsys.tui import menu
from configsys.tui.screens.profiles import ProfilesScreen
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
    return build_ctx(tmp_path_factory.mktemp('prof'))


def _both(ctx, h, w, mode, focus):
    # two FRESH models per case: a draw mutates scroll/layout state (ltop/rtop/lhmax/rhmax/reveal)
    legacy = menu._sample_profiles_state(ctx)
    fresh = menu._sample_profiles_state(ctx)
    legacy.focus = fresh.focus = focus
    # render both from the SAME resolution snapshot: _resolve reads a shared ctx.routes cache that
    # concurrent test threads can warm at different times, so two independently-built models can carry
    # a slightly different via/pin — orthogonal to the DRAW equivalence this test checks.
    fresh._res = dict(legacy._res)
    fresh._parts_cache = dict(legacy._parts_cache)
    sL, sN = BufferSurface(h, w), BufferSurface(h, w)
    menu._draw_profiles(sL, _pal(mode), legacy, legacy.ctx, '', 'profiles')
    scr = ProfilesScreen(ctx, fresh)
    scr.draw(sN, _pal(mode), scr.build_vm(ctx, (h, w)))
    return sL.grid(), sN.grid()


def _first_diff(legacy, new):
    dl, dn = dict(((y, x), (c, a)) for y, x, c, a in legacy), dict(((y, x), (c, a)) for y, x, c, a in new)
    for k in sorted(set(dl) | set(dn)):
        if dl.get(k) != dn.get(k):
            return k, dl.get(k), dn.get(k)
    return None


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('h,w', SIZES, ids=['roomy', 'tight', 'mid'])
def test_profiles_left_focus_equivalent(ctx, h, w, mode):
    legacy, new = _both(ctx, h, w, mode, focus='left')
    assert new == legacy, _first_diff(legacy, new)


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('h,w', SIZES, ids=['roomy', 'tight', 'mid'])
def test_profiles_right_focus_equivalent(ctx, h, w, mode):
    legacy, new = _both(ctx, h, w, mode, focus='right')
    assert new == legacy, _first_diff(legacy, new)


def test_profiles_build_vm_is_pure_data(ctx):
    scr = ProfilesScreen(ctx, menu._sample_profiles_state(ctx))
    vm = scr.build_vm(ctx, (40, 120))
    assert vm.status.startswith(' browse: ') and 'this box: thisbox' in vm.status
    assert vm.ctitle.startswith('components') and vm.ltitle == 'profiles'
    assert vm.legend1 and vm.legend2 and vm.nav1 and vm.nav2
    assert vm.focus == 'right'


# -- handle() behaviour ---------------------------------------------------

def test_handle_down_left_focus_bumps_lcur(ctx):
    scr = ProfilesScreen(ctx, menu._sample_profiles_state(ctx))
    scr.model.focus, scr.model.lcur = 'left', 0
    assert len(scr.model.visible_pnodes()) > 1
    km = menu._KEYMAP
    down = next(k for k in range(32, 127) if km.action_for('profiles', k) == 'down')
    intent = scr.handle(down, ctx, None, None)
    assert scr.model.lcur == 1
    assert intent.handled and not intent.dirty and intent.note is None
    assert intent.pending_notes is None and intent.open_where is None


def test_handle_switch_pane_toggles_focus(ctx):
    scr = ProfilesScreen(ctx, menu._sample_profiles_state(ctx))
    scr.model.focus = 'left'
    km = menu._KEYMAP
    tab = next(k for k in range(1, 400) if km.action_for('profiles', k) == 'switch-pane')
    scr.handle(tab, ctx, None, None)
    assert scr.model.focus == 'right'
    scr.handle(tab, ctx, None, None)
    assert scr.model.focus == 'left'


def test_handle_select_toggles_and_notes(ctx):
    scr = ProfilesScreen(ctx, menu._sample_profiles_state(ctx))
    scr.model.focus = 'right'
    km = menu._KEYMAP
    sel = next(k for k in range(1, 400) if km.action_for('profiles', k) == 'select')
    name = scr.model.vcatalog()[scr.model.rcur]
    intent = scr.handle(sel, ctx, None, None)
    assert name in scr.model.selected_comps and intent.note == '1 selected'
    intent = scr.handle(sel, ctx, None, None)
    assert not scr.model.selected_comps and intent.note == 'selection cleared'
