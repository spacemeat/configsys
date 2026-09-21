'''Render-regression for the Glue screen (docs/d2-mvvm-plan.md), in the post-oracle style: the two
MVVM seams are pinned against HAND-BUILT data — build_vm fed a fake model, draw fed a fake ViewModel —
so nothing reads routes.hu and nothing drifts. Plus handle() behaviour and an integration check that
build_vm works on the real sample.'''

from types import SimpleNamespace

import pytest

from _render_harness import RecordingPalette, build_ctx
from configsys.tui import menu
from configsys.tui.screens.glue import GlueScreen, GlueVM
from configsys.tui.surface import BufferSurface


@pytest.fixture(scope='module')
def ctx(tmp_path_factory):
    return build_ctx(tmp_path_factory.mktemp('glue'))


# -- build_vm: what the screen shows for KNOWN data ---------------------------

def _fake_model():
    '''A stand-in for a menu.GlueScreen — just the attributes build_vm reads (no ctx, no driver, no
    routes). Row tuples follow _sample_glue_state / _glue_cells: (rc, comp, target, state, source, shell).
    Two shells: bash (loader wired; one active + one changed snippet) and fish (loader off; one
    available snippet).'''
    rows = [
        (None, 'fd-glue',     '~/.config/bash/conf.d/fd.sh',     'linked',   '<repo>/shell/bash/fd.sh',     'bash'),
        (None, 'zoxide-glue', '~/.config/bash/conf.d/zoxide.sh', 'drifted',  '<repo>/shell/bash/zoxide.sh', 'bash'),
        (None, 'bat-glue',    '~/.config/fish/conf.d/bat.fish',  'template', '<repo>/shell/fish/bat.fish',  'fish'),
    ]
    display = [('hdr', 'bash', 'loader-on'), ('row', 0), ('row', 1),
               ('hdr', 'fish', 'loader-off'), ('row', 2)]
    return SimpleNamespace(
        rows=rows, display=display,
        loader={'bash': 'loader-on', 'fish': 'loader-off'},
        cur=1, top=0, hscroll=0)


def test_build_vm_cells_roles_and_status():
    scr = GlueScreen.__new__(GlueScreen)            # build_vm only reads the model — no ctx needed
    scr.model = _fake_model()
    vm = scr.build_vm(None, (40, 120))
    assert vm.has_rows
    assert vm.headers == ['component', 'state', 'conf.d', 'source']
    # a known row's four cells — state in the active/changed/available vocabulary
    assert vm.cells[0] == ['fd-glue', 'active', '~/.config/bash/conf.d/fd.sh', '<repo>/shell/bash/fd.sh']
    assert vm.cells[1][1] == 'changed'
    assert vm.cells[2][1] == 'available'
    # per-row element roles: active -> green, drifted -> amber, template -> dim
    assert vm.elems == ['installed', 'outdated', 'info_dim']
    # the display list resolved to drawable form; the cursor (row 1) sits at display index 2
    assert [e[0] for e in vm.display] == ['hdr', 'row', 'row', 'hdr', 'row']
    assert vm.display[0] == ('hdr', 'bash  loader: active ')
    assert vm.display[3] == ('hdr', 'fish  loader: inactive ')
    assert vm.display[1] == ('row', 0) and vm.display[4] == ('row', 2)
    assert vm.cur == 1 and vm.cur_disp == 2
    # column geometry: widths cover the widest cell, xs step by width + 2
    assert vm.widths[0] == len('zoxide-glue')
    assert vm.xs[1] == vm.widths[0] + 2
    assert vm.virt_w == sum(vm.widths) + 2 * (len(vm.widths) - 1)
    assert vm.status == ' 3 glue snippet(s)   1 active   1 changed (A to re-activate)   1 inactive'
    assert vm.nav


def test_build_vm_empty():
    scr = GlueScreen.__new__(GlueScreen)
    scr.model = SimpleNamespace(rows=[], display=[], loader={}, cur=0, top=0, hscroll=0)
    vm = scr.build_vm(None, (40, 120))
    assert not vm.has_rows and not vm.cells and not vm.display
    assert vm.empty_header == 'component   state   conf.d   source'
    assert vm.empty_msg == '(no installed shells / no glue in the install set)'
    assert vm.status == ' 0 glue snippet(s)   0 active   0 inactive'


# -- draw: where/how a HAND-BUILT ViewModel paints ----------------------------

def test_draw_places_title_headers_status_and_note():
    scr = GlueScreen.__new__(GlueScreen)
    scr.model = SimpleNamespace(cur=0, top=0, hscroll=0)      # the scroll fields draw writes back
    vm = GlueVM()
    vm.has_rows = True
    vm.cells = [['fd-glue', 'active', '~/.config/bash/conf.d/fd.sh', '<repo>/shell/bash/fd.sh'],
                ['bat-glue', 'available', '~/.config/fish/conf.d/bat.fish', '<repo>/shell/fish/bat.fish']]
    vm.widths = [max(len(h), max(len(r[c]) for r in vm.cells))
                 for c, h in enumerate(vm.headers)]
    vm.xs, vx = [], 0
    for wd in vm.widths:
        vm.xs.append(vx)
        vx += wd + 2
    vm.virt_w = vx - 2
    vm.elems = ['installed', 'info_dim']
    vm.display = [('hdr', 'bash  loader: active '), ('row', 0),
                  ('hdr', 'fish  loader: inactive '), ('row', 1)]
    vm.cur, vm.cur_disp = 0, 1
    vm.status = ' 2 glue snippet(s)   1 active   1 inactive'
    vm.note = 'activated fd-glue (bash)'
    vm.nav = ' j/k · q '

    surf = BufferSurface(24, 100)
    scr.draw(surf, RecordingPalette(), vm)
    rows = surf.text_rows()
    joined = '\n'.join(rows)
    assert 'glue (shell integration)' in joined                          # the panel title
    assert 'component' in joined and 'conf.d' in joined                  # column headers
    assert 'bash  loader: active ─' in joined                             # a group header, ─-padded
    assert 'fd-glue' in joined and 'bat-glue' in joined                   # the snippet rows
    assert '2 glue snippet(s)   1 active   1 inactive    activated fd-glue (bash)' in joined  # status + note
    assert rows[-1].strip() == 'j/k · q'                                  # nav footer last row
    assert scr.model.top == 0 and scr.model.hscroll == 0                  # clamps written back


def test_draw_empty_state():
    scr = GlueScreen.__new__(GlueScreen)
    scr.model = SimpleNamespace(cur=0, top=0, hscroll=0)
    vm = GlueVM()
    vm.has_rows = False
    vm.empty_header = 'component   state   conf.d   source'
    vm.empty_msg = '(no installed shells / no glue in the install set)'
    vm.status = ' 0 glue snippet(s)   0 active   0 inactive'
    vm.nav = ' q '
    surf = BufferSurface(24, 100)
    scr.draw(surf, RecordingPalette(), vm)
    joined = '\n'.join(surf.text_rows())
    assert 'component   state   conf.d   source' in joined
    assert '(no installed shells / no glue in the install set)' in joined
    assert '0 glue snippet(s)   0 active   0 inactive' in joined


def test_build_vm_on_the_real_sample(ctx):
    # integration: build_vm runs end-to-end on the shipped sample state
    scr = GlueScreen(ctx, menu._sample_glue_state(ctx))
    vm = scr.build_vm(ctx, (40, 200))
    assert vm.has_rows and vm.cells and len(vm.cells[0]) == len(vm.headers)
    assert len(vm.elems) == len(vm.cells) == len(scr.model.rows)
    assert 'glue snippet(s)' in vm.status and vm.nav


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
