'''Render-regression for the Glue screen (docs/done/d2-mvvm-plan.md), in the post-oracle style: the two
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
    rows = [   # component glue links as conf.d/50-<name>.<ext>
        (None, 'fd-glue',     '~/.config/bash/conf.d/50-fd.sh',     'linked',   '<repo>/shell/bash/fd.sh',     'bash'),
        (None, 'zoxide-glue', '~/.config/bash/conf.d/50-zoxide.sh', 'drifted',  '<repo>/shell/bash/zoxide.sh', 'bash'),
        (None, 'bat-glue',    '~/.config/fish/conf.d/50-bat.fish',  'template', '<repo>/shell/fish/bat.fish',  'fish'),
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
    assert vm.cells[0] == ['fd-glue', 'active', '~/.config/bash/conf.d/50-fd.sh', '<repo>/shell/bash/fd.sh']
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
    vm.cells = [['fd-glue', 'active', '~/.config/bash/conf.d/50-fd.sh', '<repo>/shell/bash/fd.sh'],
                ['bat-glue', 'available', '~/.config/fish/conf.d/50-bat.fish', '<repo>/shell/fish/bat.fish']]
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
    assert intent.note is None and not scr.model.dirty
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


# -- USER glue (the user.d namespace: `glue add` snippets + activated staged blocks) ----------

def test_build_vm_labels_user_glue_rows():
    scr = GlueScreen.__new__(GlueScreen)
    m = _fake_model()
    m.rows = m.rows[:2] + [
        (None, '(user) aliases', '~/.config/bash/conf.d/90-aliases.sh', 'linked',
         '<plugin>/shell/bash/user.d/aliases.sh', 'bash', True),
        (None, '(user) staged', '~/.config/bash/conf.d/90-staged.sh', 'unlinked',
         '<local>/shell/bash/user.d/staged.sh', 'bash', True)] + m.rows[2:]
    m.display = [('hdr', 'bash', 'loader-on'), ('row', 0), ('row', 1), ('row', 2), ('row', 3),
                 ('hdr', 'fish', 'loader-off'), ('row', 4)]
    scr.model = m
    vm = scr.build_vm(None, (40, 120))
    assert vm.cells[2] == ['(user) aliases', 'active', '~/.config/bash/conf.d/90-aliases.sh',
                           '<plugin>/shell/bash/user.d/aliases.sh']
    assert vm.cells[3][1] == 'inactive' and vm.elems[3] == 'info_dim'     # unlinked -> inactive
    assert vm.elems[2] == 'installed'
    assert vm.status.endswith('(2 your own user glue)')


class _FakeGlueDrv:
    def __init__(self, entries=()):
        self.entries = list(entries)
        self.deployed = []
        self.installed = []

    def user_glue_entries(self):
        return self.entries

    def _user_glue_roots(self):
        from pathlib import Path
        return [Path('/store/glue')]

    def deploy_user_glue(self, shell):
        self.deployed.append(shell)

    def install(self, rc, only_shells=None):
        self.installed.append((rc, tuple(only_shells or ())))


def test_model_appends_user_rows_under_installed_shells(ctx):
    from pathlib import Path
    gs = menu.GlueScreen.__new__(menu.GlueScreen)
    gs.ctx = ctx
    gs.gd = _FakeGlueDrv([
        ('bash', Path('/store/glue/shell/bash/user.d/aliases.sh'),
         Path('/h/.config/bash/conf.d/90-aliases.sh'), 'linked'),
        ('elvish', Path('/store/glue/shell/elvish/user.d/x.elv'),
         Path('/h/.config/elvish/conf.d/90-x.elv'), 'unlinked')])     # elvish not installed -> skipped
    rows = gs._user_rows({'bash': []})
    (row,) = rows['bash']
    assert menu._is_user_glue(row) and row[1] == '(user) aliases' and row[3] == 'linked'
    assert row[2].endswith('conf.d/90-aliases.sh') and row[4].endswith('shell/bash/user.d/aliases.sh')
    assert 'elvish' not in rows


def _user_row_screen(ctx):
    scr = GlueScreen(ctx, menu._sample_glue_state(ctx))
    gs = scr.model
    gs.gd = _FakeGlueDrv()
    gs.reload = lambda: None                                  # keep the hand-built rows
    gs.cur = next(i for i, r in enumerate(gs.rows) if menu._is_user_glue(r))
    return scr, gs


def test_handle_user_glue_activate_relinks_and_deactivate_explains(ctx, monkeypatch):
    from contextlib import nullcontext
    from configsys.tui.screens import glue as glue_mod
    monkeypatch.setattr(glue_mod, 'suspended', lambda _s: nullcontext())
    scr, gs = _user_row_screen(ctx)
    km = menu._KEYMAP
    act = next(k for k in range(32, 127) if km.action_for('glue', k) == 'activate')
    deact = next(k for k in range(32, 127) if km.action_for('glue', k) == 'deactivate')
    intent = scr.handle(act, ctx, None, None)
    assert gs.gd.deployed == ['bash'] and 'user glue' in intent.note and not gs.dirty
    intent = scr.handle(deact, ctx, None, None)
    assert 'your own glue' in intent.note and gs.gd.deployed == ['bash']   # nothing unlinked
    assert not intent.note.startswith('error')


def test_handle_activate_group_includes_user_glue(ctx, monkeypatch):
    from contextlib import nullcontext
    from configsys.tui.screens import glue as glue_mod
    monkeypatch.setattr(glue_mod, 'suspended', lambda _s: nullcontext())
    scr, gs = _user_row_screen(ctx)
    gs.rows = [r for r in gs.rows if menu._is_user_glue(r) or r[5] != 'bash'] + \
        [(SimpleNamespace(key='glue\\fd', comp='fd-glue'), 'fd-glue', 't', 'template', 's', 'bash')]
    gs.cur = 0
    grp = next(k for k in range(32, 127) if menu._KEYMAP.action_for('glue', k) == 'activate-group')
    intent = scr.handle(grp, ctx, None, None)
    assert gs.gd.deployed == ['bash'] and len(gs.gd.installed) == 1
    assert '2 snippet(s)' in intent.note
