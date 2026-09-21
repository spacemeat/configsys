'''DEMONSTRATION of the post-oracle render-regression style (docs/d2-mvvm-plan.md).

The legacy-vs-legacy equivalence tests proved the migration neutral — a one-time job. Going forward,
render regressions are pinned WITHOUT the legacy painters and WITHOUT golden snapshots, by testing the
two MVVM seams against HAND-BUILT data:

  * build_vm  — feed a screen a fake model with known rows; assert the ViewModel it produces (what the
                screen decides to show). No live routes.hu, so nothing drifts.
  * draw      — feed draw a hand-built ViewModel directly; assert a few representative painted cells
                (where/how it paints). The VM is fixed input, so the expected cells are stable.

This file demonstrates the pattern on the Plugins screen. The plan is to give every screen a file like
this and then delete test/_legacy_render.py + the *_equivalent tests.
'''

from types import SimpleNamespace

from configsys.tui.screens.plugins import PluginsScreen, PluginsVM
from configsys.tui.surface import BufferSurface


class _FakePal:
    '''A trivial palette: every attr is a readable ('role', selected) token. Enough to assert WHICH
    role painted a cell without any curses or real color math.'''
    gradient = False
    have256 = True

    def new_frame(self):
        pass

    def use_page(self, _p):
        pass

    def style(self, element, *a, selected=False, **k):
        return ('style', element, bool(selected))

    def fill(self, *a, selected=False, **k):
        return ('fill', bool(selected))


def _fake_model():
    '''A hand-built stand-in for a PluginScreen — just the attributes build_vm reads. No ctx, no git,
    no routes. Two rows: a healthy up-to-date primary, and one with an available update.'''
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
        remote={'x': 'v1.0', 'y': 'v0.9'},          # science: remote newer than ref -> 'outdated' role
        cur=0, top=0, hscroll=0, focus='table',
        diff_files=[], diff_note='', dfile=0, dtop=0, dhscroll=0,
        cur_row=lambda: rows[0])


# -- build_vm: assert WHAT the screen shows for known data --------------------

def test_build_vm_rows_and_roles():
    scr = PluginsScreen.__new__(PluginsScreen)      # no ctx needed — build_vm only reads the model
    scr.model = _fake_model()

    # plugins.dir_name maps a source to a dir; the fake remote is keyed by the last path segment.
    import configsys.plugins as plugins
    scr.model.remote = {plugins.dir_name('github:me/x'): 'v1.0',
                        plugins.dir_name('github:org/y'): 'v0.9'}

    vm = scr.build_vm(None, (40, 120))
    assert vm.has_rows
    # the name cell carries the ★ for the primary, and the plain name for the other
    assert vm.cells[0][0] == '★mytools'
    assert vm.cells[1][0] == 'science'
    # role of the remote-ref column: up-to-date -> 'installed' (green), update available -> 'outdated'
    remote_col = vm.headers.index('remote-ref')
    assert vm.elems[0][remote_col] == 'installed'
    assert vm.elems[1][remote_col] == 'outdated'
    assert '2 plugin(s)' in vm.status


# -- draw: assert WHERE/HOW a hand-built VM paints ----------------------------

def test_draw_places_headers_and_status():
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
    scr.draw(surf, _FakePal(), vm)
    rows = surf.text_rows()
    joined = '\n'.join(rows)
    # the column headers, the empty-state message, and the status note all render at known places
    assert 'plugins (tree)' in joined            # the table panel title
    assert '(no plugins declared — a to add)' in joined
    assert '0 plugin(s) · focus: table    synced all' in joined   # status + appended note
    assert rows[-1].strip() == 'tab focus · q'   # the nav footer is the last row
