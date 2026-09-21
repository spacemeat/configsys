'''Render-regression for the Plugins screen (docs/d2-mvvm-plan.md), in the post-oracle style: the two
MVVM seams are pinned against HAND-BUILT data — build_vm fed a fake model, draw fed a fake ViewModel —
so nothing reads routes.hu and nothing drifts. Plus handle() behaviour and an integration check that
build_vm works on the real sample.'''

from types import SimpleNamespace

import pytest

from _render_harness import RecordingPalette, build_ctx
from configsys.tui import menu
from configsys.tui.screens.plugins import PluginsScreen, PluginsVM
from configsys.tui.surface import BufferSurface


@pytest.fixture(scope='module')
def ctx(tmp_path_factory):
    return build_ctx(tmp_path_factory.mktemp('plug'))


# -- build_vm: what the screen shows for KNOWN data ---------------------------

def _fake_model():
    '''A stand-in for a PluginScreen — just the attributes build_vm reads (no ctx, no git, no routes).
    Two rows: a healthy up-to-date primary and one with an available update.'''
    import configsys.plugins as plugins
    rows = [
        {'primary': True, 'name': 'mytools', 'source': 'github:me/x', 'ref': 'v1.0', 'abi_ok': True,
         'requires_abi': 2, 'code_state': 'trusted', 'has_code': True, 'provides': {'driver': ['foo']},
         'synced': True, 'checksum': 'ok'},
        {'primary': False, 'name': 'science', 'source': 'github:org/y', 'ref': 'v0.4', 'abi_ok': True,
         'requires_abi': 2, 'code_state': 'none', 'has_code': False, 'provides': {}, 'synced': True,
         'checksum': 'ok'},
    ]
    tree = [{'depth': 0, 'last': [True], 'decl': {}}, {'depth': 0, 'last': [True], 'decl': {}}]
    return SimpleNamespace(
        rows=rows, tree=tree,
        remote={plugins.dir_name('github:me/x'): 'v1.0',      # up to date
                plugins.dir_name('github:org/y'): 'v0.9'},    # newer than ref -> update available
        cur=0, top=0, hscroll=0, focus='table',
        diff_files=[], diff_note='', dfile=0, dtop=0, dhscroll=0,
        cur_row=lambda: rows[0])


def test_build_vm_rows_and_roles():
    scr = PluginsScreen.__new__(PluginsScreen)      # build_vm only reads the model — no ctx needed
    scr.model = _fake_model()
    vm = scr.build_vm(None, (40, 120))
    assert vm.has_rows
    assert vm.cells[0][0] == '★mytools'             # primary carries the ★; the name column is first
    assert vm.cells[1][0] == 'science'
    remote_col = vm.headers.index('remote-ref')
    assert vm.elems[0][remote_col] == 'installed'   # up-to-date -> green
    assert vm.elems[1][remote_col] == 'outdated'    # update available -> amber
    assert '2 plugin(s)' in vm.status


# -- draw: where/how a HAND-BUILT ViewModel paints ----------------------------

def test_draw_places_headers_status_and_note():
    scr = PluginsScreen.__new__(PluginsScreen)
    scr.model = SimpleNamespace(focus='table', rows=[], top=0, hscroll=0, cur=0,
                                dtop=0, dhscroll=0, dfile=0, diff_files=[])
    vm = PluginsVM()
    vm.has_rows = False
    vm.empty_msg = '(no plugins declared — a to add)'
    vm.diff_has_files = False
    vm.diff_msg = 'nothing to review'
    vm.status = ' 0 plugin(s) · focus: table'
    vm.note = 'synced all'
    vm.nav = ' tab focus · q '

    surf = BufferSurface(24, 100)
    scr.draw(surf, RecordingPalette(), vm)
    joined = '\n'.join(surf.text_rows())
    assert 'plugins (tree)' in joined                                  # the table panel title
    assert '(no plugins declared — a to add)' in joined                # empty-state message
    assert '0 plugin(s) · focus: table    synced all' in joined        # status + appended note
    assert surf.text_rows()[-1].strip() == 'tab focus · q'             # nav footer last row


def test_build_vm_on_the_real_sample(ctx):
    # integration: build_vm runs end-to-end on the shipped sample (exercises plugins.dir_name etc.)
    scr = PluginsScreen(ctx, menu._sample_plugins_state(ctx))
    vm = scr.build_vm(ctx, (40, 200))
    assert vm.has_rows and vm.cells and len(vm.cells[0]) == len(vm.headers)
    assert vm.diff_has_files and vm.diff_lines            # the sample carries a mocked diff
    assert 'plugin(s)' in vm.status and vm.nav


# -- handle() behaviour -------------------------------------------------------

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
