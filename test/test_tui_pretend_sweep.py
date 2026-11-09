'''review-2026-11-2 tui-screens-11 — every mutating TUI key writes nothing under --pretend.

The CLI sweep (test_pretend_sweep) drives every verb through `main`; this drives every screen-scope
action key of all seven screens through its Screen.handle, on the same populated sandbox home, with
the modals answering their FIRST option (usually the "yes, do it" one), the input box typing `x`, and
the terminal hand-off stubbed. The whole home tree is compared after each key.'''

import contextlib
import curses
import shutil

import pytest

from _render_harness import RecordingPalette
import test_pretend_sweep
from test_pretend_sweep import _changes, _pretend_ctx, _snapshot

from configsys.tui import flows, keyspec, menu, modals
from configsys.tui.surface import BufferSurface

sandbox = test_pretend_sweep.sandbox           # the CLI sweep's populated home, as a fixture here

pytestmark = [pytest.mark.real_runner, pytest.mark.skipif(shutil.which('git') is None, reason='git not available')]


class _Scr(BufferSurface):
    def getch(self):
        return 27                                    # any inline modal loop: Esc


def _first(*a, **k):
    return 0


def _typed(*a, **k):
    return ('x', False) if k.get('toggle') else 'x'


@pytest.fixture
def tui(sandbox, monkeypatch, capsys):
    home, _dry = sandbox
    for mod in (menu, modals, flows):
        for name, fake in (('_popup_choose', _first), ('_input_box', _typed), ('_order_list', lambda *a, **k: None),
                           ('_machines_modal', lambda s, p, c, t: (set(t), '')),
                           ('_component_machines_modal', lambda *a, **k: ''),
                           ('_attr_filter_modal', lambda *a, **k: None)):
            if hasattr(mod, name) or name in getattr(mod, '_MOVED', {}):
                monkeypatch.setattr(mod, name, fake, raising=False)
    from configsys.tui.screens import components, config, dotfiles, glue, plugins, profiles, theme
    for mod in (flows, components, config, dotfiles, glue, plugins, profiles, theme):
        if hasattr(mod, 'suspended'):
            monkeypatch.setattr(mod, 'suspended', lambda _s: contextlib.nullcontext())
    monkeypatch.setattr(curses, 'flushinp', lambda: None)
    monkeypatch.setattr(curses, 'curs_set', lambda *_a: None)
    monkeypatch.setattr('builtins.input', lambda *a: 'y')
    monkeypatch.setattr(menu, '_KEYMAP', keyspec.shipped_keymap())
    ctx = _pretend_ctx(home)
    capsys.readouterr()
    return home, ctx


def _keys(scope):
    km = keyspec.shipped_keymap()
    nav = keyspec.KNOWN_ACTIONS['global']
    for action in sorted(keyspec.KNOWN_ACTIONS[scope] - nav):
        codes = km.keys_for(scope, action)
        if codes:
            yield action, codes[0]


def test_every_screen_key_writes_nothing_under_pretend(tui, capsys):
    home, ctx = tui
    from configsys.tui.screens.components import ComponentsScreen
    from configsys.tui.screens.config import ConfigScreen
    from configsys.tui.screens.dotfiles import DotfilesScreen
    from configsys.tui.screens.glue import GlueScreen
    from configsys.tui.screens.plugins import PluginsScreen
    from configsys.tui.screens.profiles import ProfilesScreen
    from configsys.tui.screens.theme import ThemeScreen
    cfg, _req, _units, ledger, states = ctx.load_pipeline()
    st, layouts, transitive = menu._components_model(ctx, cfg, states, 'tracked')
    ms = menu.MenuState(st, layouts, transitive)
    ms.descriptions = {}
    ctx._primary_state, ctx._primary_push_mode, ctx._reboot_pending = None, 'manual', (False, '')
    pal, scr = RecordingPalette(), _Scr(40, 140)
    screens = {'components': ComponentsScreen(ctx, ms), 'profiles': ProfilesScreen(ctx),
               'plugins': PluginsScreen(ctx), 'glue': GlueScreen(ctx), 'dotfiles': DotfilesScreen(ctx),
               'config': ConfigScreen(ctx), 'theme': ThemeScreen(ctx)}
    wrote, crashed, driven = {}, {}, 0
    before = _snapshot(home)
    for sid, screen in screens.items():
        for action, code in _keys(sid):
            for setup in (None, 'right') if sid == 'profiles' else (None,):
                if setup:
                    screen.model.focus = setup
                driven += 1
                try:
                    if sid == 'components':
                        screen.handle(code, ctx, scr, pal, cfg, ledger)
                    else:
                        screen.handle(code, ctx, scr, pal)
                except Exception as e:                     # noqa: BLE001 — a key must never crash
                    crashed[f'{sid}:{action}'] = repr(e)
                after = _snapshot(home)
                ch = _changes(before, after)
                if ch:
                    wrote[f'{sid}:{action}{"@" + setup if setup else ""}'] = ch
                before = after
    capsys.readouterr()
    assert driven >= 60                                   # every screen's action keys ran
    assert wrote == {}
    assert crashed == {}
