'''Render-regression for the Dotfiles screen (docs/d2-mvvm-plan.md), in the post-oracle style: the two
MVVM seams are pinned against HAND-BUILT data — build_vm fed a fake model, draw fed a fake ViewModel —
so nothing reads routes.hu and nothing drifts. Plus handle() behaviour and an integration check that
build_vm works on the real sample.'''

from types import SimpleNamespace

import pytest

from _render_harness import RecordingPalette, build_ctx
from configsys.tui import menu
from configsys.tui.screens.dotfiles import DotfilesScreen, DotfilesVM
from configsys.tui.surface import BufferSurface


@pytest.fixture(scope='module')
def ctx(tmp_path_factory):
    return build_ctx(tmp_path_factory.mktemp('dotf'))


# -- build_vm: what the screen shows for KNOWN data ---------------------------

def _fake_model():
    '''A stand-in for a menu.DotfilesScreen — just the attributes build_vm reads (no ctx, no driver,
    no routes). Three rows covering each display state: a linked (managed) config, a real on-system
    file we don't manage (unmanaged, at risk), and an empty one (no config).'''
    rows = [   # (rc(.comp), name, target, raw-state, source, capturable)
        (SimpleNamespace(comp='neovim-dotfiles'), 'neovim', '~/.config/nvim',       'linked',    '<plugin>/neovim.cfs', False),
        (SimpleNamespace(comp='git-dotfiles'),    'git',    '~/.gitconfig',         'unmanaged', 'gitconfig',           True),
        (SimpleNamespace(comp='bat-dotfiles'),    'bat',    '~/.config/bat/config', 'empty',     'bat.cfs',             False),
    ]
    return SimpleNamespace(
        rows=rows, display=[('row', 0), ('row', 1), ('row', 2)],
        cur=0, top=0, hscroll=0,
        cur_row=lambda: rows[0])


def test_build_vm_rows_roles_and_status():
    scr = DotfilesScreen.__new__(DotfilesScreen)    # build_vm only reads the model — no ctx needed
    scr.model = _fake_model()
    vm = scr.build_vm(None, (40, 200))
    assert vm.has_rows
    assert vm.headers == ['component', 'state', 'link', 'source']
    assert len(vm.cells) == len(vm.elems) == len(vm.display) == 3
    # the unmanaged row: `!` flag + collapsed display state, then link target and source verbatim
    assert vm.cells[1] == ['git-dotfiles', '! unmanaged', '~/.gitconfig', 'gitconfig']
    assert vm.cells[0][1] == '  managed'             # linked -> managed, no flag
    assert vm.cells[2][1] == '  no config'           # empty -> no config
    assert vm.elems == ['installed', 'outdated', 'info_dim']   # managed / unmanaged / no config
    # column geometry: each column is as wide as its longest cell, two-space gutters between
    assert vm.widths[0] == len('neovim-dotfiles') and vm.widths[2] == len('~/.config/bat/config')
    assert vm.xs[0] == 0 and vm.xs[1] == vm.widths[0] + 2
    assert vm.virt_w == sum(vm.widths) + 2 * (len(vm.widths) - 1)
    assert '3 config target(s)' in vm.status
    assert '1 managed' in vm.status and '1 unmanaged' in vm.status and '1 no config' in vm.status
    assert '! 1 unmanaged file(s) at risk' in vm.status
    assert vm.nav


def test_build_vm_no_risk_clause_without_unmanaged_rows():
    scr = DotfilesScreen.__new__(DotfilesScreen)
    m = _fake_model()
    m.rows = [m.rows[0], m.rows[2]]                   # managed + no config only
    m.display = [('row', 0), ('row', 1)]
    scr.model = m
    vm = scr.build_vm(None, (40, 200))
    assert '2 config target(s)' in vm.status
    assert 'unmanaged' not in vm.status and 'at risk' not in vm.status


def test_build_vm_empty():
    scr = DotfilesScreen.__new__(DotfilesScreen)
    scr.model = SimpleNamespace(rows=[], display=[], cur=0, top=0, hscroll=0)
    vm = scr.build_vm(None, (40, 200))
    assert not vm.has_rows and vm.empty_msg == '(no dotfiles in the active profiles)'
    assert vm.cells == [] and vm.elems == []
    assert vm.status.strip() == '0 config target(s)'


# -- draw: where/how a HAND-BUILT ViewModel paints ----------------------------

def test_draw_places_headers_rows_status_and_note():
    scr = DotfilesScreen.__new__(DotfilesScreen)
    scr.model = SimpleNamespace(cur=0, top=0, hscroll=0)    # only the scroll fields draw writes/reads
    vm = DotfilesVM()
    vm.has_rows = True
    vm.cells = [['git-dotfiles', '! unmanaged', '~/.gitconfig', 'gitconfig'],
                ['bat-dotfiles', '  no config', '~/.config/bat', 'bat.cfs']]
    vm.widths = [12, 11, 13, 9]
    vm.xs = [0, 14, 27, 42]
    vm.virt_w = 51
    vm.elems = ['outdated', 'info_dim']
    vm.display = [('row', 0), ('row', 1)]
    vm.status = ' 2 config target(s)   1 unmanaged   1 no config'
    vm.note = 'ZZ_NOTE_MARKER_ZZ'
    vm.nav = ' m/M manage · q '

    surf = BufferSurface(24, 200)
    scr.draw(surf, RecordingPalette(), vm)
    rows = surf.text_rows()
    joined = '\n'.join(rows)
    assert 'dotfiles (config state)' in joined                         # the panel title
    assert 'component     state        link           source' in joined   # each header at its column x
    assert 'git-dotfiles  ! unmanaged  ~/.gitconfig   gitconfig' in joined
    assert 'bat-dotfiles    no config  ~/.config/bat  bat.cfs' in joined
    assert '2 config target(s)   1 unmanaged   1 no config    ZZ_NOTE_MARKER_ZZ' in rows[-2]   # status + note
    assert rows[-1].strip() == 'm/M manage · q'                        # nav footer last row


def test_draw_empty_state():
    scr = DotfilesScreen.__new__(DotfilesScreen)
    scr.model = SimpleNamespace(cur=0, top=0, hscroll=0)
    vm = DotfilesVM()
    vm.has_rows = False
    vm.empty_msg = '(no dotfiles in the active profiles)'
    vm.status = ' 0 config target(s)   '
    vm.nav = ' q '
    surf = BufferSurface(24, 200)
    scr.draw(surf, RecordingPalette(), vm)
    joined = '\n'.join(surf.text_rows())
    assert 'component   state   link   source' in joined               # headers still drawn (3-space join)
    assert '(no dotfiles in the active profiles)' in joined
    assert '0 config target(s)' in joined


def test_build_vm_on_the_real_sample(ctx):
    # integration: build_vm runs end-to-end on the shipped sample
    scr = DotfilesScreen(ctx, menu._sample_dotfiles_state(ctx))
    vm = scr.build_vm(ctx, (40, 200))
    assert vm.has_rows and vm.cells and len(vm.cells[0]) == len(vm.headers)
    assert len(vm.elems) == len(vm.cells) == len(vm.display) == 4
    assert vm.elems == ['installed', 'outdated', 'info_dim', 'installed']   # managed/unmanaged/no config/managed
    assert '4 config target(s)' in vm.status and '! 1 unmanaged file(s) at risk' in vm.status
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
