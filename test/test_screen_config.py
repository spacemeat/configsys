'''Render-regression for the Config (machine settings) screen (docs/d2-mvvm-plan.md), in the
post-oracle style: the two MVVM seams are pinned against HAND-BUILT data — build_vm fed a fake
model (a tiny settings catalog), draw fed a fake ViewModel — so nothing reads routes.hu and nothing
drifts. Plus handle() behaviour and an integration check that build_vm works on the real sample.'''

from pathlib import Path
from types import SimpleNamespace

import pytest

from _render_harness import RecordingPalette, build_ctx
from configsys.tui import menu
from configsys.tui.screens.base import Intent
from configsys.tui.screens.config import ConfigScreen, ConfigVM
from configsys.tui.surface import BufferSurface


@pytest.fixture(scope='module')
def ctx(tmp_path_factory):
    return build_ctx(tmp_path_factory.mktemp('conf'))


# -- build_vm: what the screen shows for KNOWN data ---------------------------

_FAKE_CONFIG_FILE = '/nowhere/configsys/configsys.hu'     # not under ~ -> shown verbatim; absent ->
                                                          # no plugins declared -> has_primary False


def _fake_model():
    '''A stand-in for a menu.ConfigScreen — just the attributes build_vm reads (no ctx, no
    actions.config_settings, no routes). Three settings covering the three `default`-column
    states: a machine-local bool override, an untouched scalar, and an env-overridden scalar.'''
    settings = {
        'reboot-advice': {'kind': 'bool', 'value': True, 'nature': 'machine',
                          'desc': 'advise a reboot after ops when the OS says one is pending',
                          'man': 'reboot-advice', 'home': 'local', 'source': 'top config',
                          'target': 'top config'},
        'scope': {'kind': 'scalar', 'value': None, 'nature': 'machine',
                  'desc': 'install scope: user or system', 'man': 'scope',
                  'home': None, 'source': None, 'target': None},
        'splash': {'kind': 'scalar', 'value': 'ocean', 'nature': 'machine',
                   'desc': 'startup wait-screen provider', 'man': 'splash',
                   'home': None, 'source': 'env CONFIGSYS_SPLASH', 'target': 'top config'},
    }
    return SimpleNamespace(settings=settings, keys=list(settings), cur=0, top=0)


def _stub_ctx():
    '''Only ctx.paths.user_config_file is read (for has_primary + the local store path); pointing it
    at a nonexistent file keeps build_vm hermetic — plugins.declared() -> [] without touching disk.'''
    return SimpleNamespace(paths=SimpleNamespace(user_config_file=Path(_FAKE_CONFIG_FILE)))


def test_build_vm_settings_states_and_stores():
    scr = ConfigScreen.__new__(ConfigScreen)          # build_vm only reads the model + ctx.paths
    scr.model = _fake_model()
    vm = scr.build_vm(_stub_ctx(), (40, 120))
    assert not vm.has_primary
    assert vm.names == ['reboot-advice', 'scope', 'splash']
    assert vm.values == ['true', 'user (default)', 'ocean']       # _setting_str per kind/key
    assert vm.states == [('custom', 'installed'),                 # home=local -> green
                         ('default', 'info_dim'),                 # untouched -> dim
                         ('env', 'outdated')]                     # env override -> amber
    assert vm.stores == [(_FAKE_CONFIG_FILE, '(machine-local)', 'scope'),     # nature-default store
                         (_FAKE_CONFIG_FILE, '(machine-local)', 'scope'),
                         ('CONFIGSYS_SPLASH', '(env override)', 'header')]    # relocated -> header
    assert vm.descs[1] == ['install scope: user or system'] and all(vm.descs)
    assert vm.mans == ['man: reboot-advice', 'man: scope', 'man: splash']
    # the cursor's setting carries a target -> status names it (no actions.edit_target call)
    assert vm.status == ' reboot-advice: edits → top config'
    assert vm.nav
    assert scr.model.top == 0 and scr.model.cur == 0     # build_vm never scrolls the model


def test_build_vm_wraps_long_descriptions_to_the_panel():
    scr = ConfigScreen.__new__(ConfigScreen)
    scr.model = _fake_model()
    scr.model.settings['scope']['desc'] = 'word ' * 40           # ~200 cols of prose
    vm = scr.build_vm(_stub_ctx(), (40, 60))                     # interior 58 -> wrap at 54
    assert len(vm.descs[1]) > 1 and all(len(line) <= 54 for line in vm.descs[1])


# -- draw: where/how a HAND-BUILT ViewModel paints ----------------------------

def test_draw_places_headers_rows_status_and_note():
    scr = ConfigScreen.__new__(ConfigScreen)
    keys = ['reboot-advice', 'scope']
    scr.model = SimpleNamespace(keys=keys, cur=0, top=0)         # the scroll fields draw writes
    vm = ConfigVM()
    vm.names = keys
    vm.values = ['true', 'user (default)']
    vm.states = [('custom', 'installed'), ('default', 'info_dim')]
    vm.stores = [('~/.config/configsys/configsys.hu', '(machine-local)', 'scope'),
                 ('~/.config/configsys/configsys.hu', '(machine-local)', 'scope')]
    vm.descs = [['advise a reboot after ops'], ['install scope: user or system']]
    vm.mans = ['man: reboot-advice', 'man: scope']
    vm.status = ' reboot-advice: edits → top config'
    vm.note = 'ZZ_NOTE_MARKER_ZZ'
    vm.nav = ' j/k move · q quit '

    surf = BufferSurface(30, 120)
    scr.draw(surf, RecordingPalette(), vm)
    rows = surf.text_rows()
    joined = '\n'.join(rows)
    assert 'machine settings' in joined                           # the panel title
    header = next(r for r in rows if 'name' in r and 'value' in r and 'default' in r)
    assert 'store' in header                                      # all four column labels, one row
    name_row = rows[rows.index(header) + 1]                       # first setting block follows
    assert 'reboot-advice' in name_row and 'true' in name_row and 'custom' in name_row
    assert '(machine-local)' in name_row                          # store suffix stays visible
    assert 'advise a reboot after ops' in joined and 'man: reboot-advice' in joined
    assert 'reboot-advice: edits → top config    ZZ_NOTE_MARKER_ZZ' in rows[-2]   # status + note
    assert rows[-1].strip() == 'j/k move · q quit'                # nav footer last row
    assert scr.model.top == 0                                     # everything fit -> no scroll


def test_draw_scrolls_to_keep_the_cursor_block_in_view():
    scr = ConfigScreen.__new__(ConfigScreen)
    keys = [f'setting-{i}' for i in range(12)]
    scr.model = SimpleNamespace(keys=keys, cur=11, top=0)
    vm = ConfigVM()
    vm.names = keys
    vm.values = ['x'] * 12
    vm.states = [('default', 'info_dim')] * 12
    vm.stores = [('~/cfg.hu', '(machine-local)', 'scope')] * 12
    vm.descs = [['d']] * 12
    vm.mans = ['man: x'] * 12
    vm.status, vm.nav = ' s', ' n '
    surf = BufferSurface(20, 120)                                 # 12 blocks x 4 rows won't fit
    scr.draw(surf, RecordingPalette(), vm)
    assert scr.model.top > 0                                      # keep-cursor scroll written back
    assert 'setting-11' in '\n'.join(surf.text_rows())


def test_build_vm_on_the_real_sample(ctx):
    # integration: build_vm runs end-to-end on the real settings catalog (actions.config_settings)
    scr = ConfigScreen(ctx, menu.ConfigScreen(ctx))
    vm = scr.build_vm(ctx, (40, 200))
    n = len(scr.model.keys)
    assert n and len(vm.names) == len(vm.values) == len(vm.states) == len(vm.stores) == n
    assert all(len(s) == 2 for s in vm.states) and all(len(s) == 3 for s in vm.stores)
    assert 'edits →' in vm.status and vm.nav


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
