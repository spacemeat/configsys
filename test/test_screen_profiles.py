'''Render-regression for the Profiles screen (docs/d2-mvvm-plan.md), post-oracle style. Profiles'
build_vm is light (titles/status/legends/nav) and its draw reads the model + the live catalog, so the
assertions here pin the ROUTES-INDEPENDENT chrome (panel titles, status prefix, the footers, the note)
rather than specific catalog rows — nothing drifts when routes.hu changes. The fixture is the hermetic
`_sample_profiles_state` (its warm-cache thread is aborted + resolutions pre-seeded). Plus handle().'''

import pytest

from _render_harness import RecordingPalette, build_ctx
from configsys.tui import menu
from configsys.tui.screens.profiles import ProfilesScreen
from configsys.tui.surface import BufferSurface


@pytest.fixture(scope='module')
def ctx(tmp_path_factory):
    return build_ctx(tmp_path_factory.mktemp('prof'))


# -- build_vm: the (routes-independent) chrome fields -------------------------

def test_build_vm_titles_status_and_legends(ctx):
    scr = ProfilesScreen(ctx, menu._sample_profiles_state(ctx))
    vm = scr.build_vm(ctx, (40, 120))
    assert vm.ltitle == 'profiles'
    assert vm.ctitle.startswith('components')
    assert vm.status.startswith(' browse: ') and 'this box: thisbox' in vm.status
    assert vm.legend1 and vm.legend2 and vm.nav1 and vm.nav2
    assert vm.focus == 'right'


# -- draw: the chrome paints (catalog content is asserted by build_vm, not here) --

def test_draw_paints_panels_status_and_note(ctx):
    scr = ProfilesScreen(ctx, menu._sample_profiles_state(ctx))
    vm = scr.build_vm(ctx, (40, 160))
    vm.note = 'ZZ_PROFILE_NOTE_ZZ'
    surf = BufferSurface(40, 160)
    scr.draw(surf, RecordingPalette(), vm)
    joined = '\n'.join(surf.text_rows())
    assert 'profiles' in joined                       # the left (browse) panel title
    assert 'components' in joined                      # the right (catalog) panel title
    assert 'browse:' in joined                         # the status line prefix
    assert 'ZZ_PROFILE_NOTE_ZZ' in joined              # the appended transient note


# -- handle() behaviour -------------------------------------------------------

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
