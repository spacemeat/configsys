'''The TUI install-method picker (Phase 3b): the `m` key lists a component's candidate methods
and writes a binding-pin to the top config. Curses I/O is patched out (suspended -> nullcontext,
input stubbed); the pin-write path and reload-invalidation are what matter here.'''

import builtins
import contextlib

from configsys import plugins
from configsys.app import Context, build_parser
from configsys.tui import menu
from configsys.tui.menu import COMPONENT, PROFILE, UNIT, Node, _row_component


def _ctx(tmp_path, *extra):
    args = build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', *extra, 'inspect'])
    return Context(args)


def _menu_on(ctx, component):
    cfg, _r, _u, _l, states = ctx.load_pipeline()
    ms = menu.MenuState(states, menu._profile_comps(cfg))
    ms.cursor = next(i for i, n in enumerate(ms.rows) if _row_component(n) == component)
    return ms


def _steam_home(tmp_path):
    d = tmp_path / '.config' / 'configsys'
    d.mkdir(parents=True)
    (d / 'configsys.hu').write_text('{ configs: [ games ]  profiles: { games: [ steam, btop ] } }')
    return d


def test_row_component_parses_node_ids():
    assert _row_component(Node(COMPONENT, 'c:games:steam', 'steam', 1, [])) == 'steam'
    assert _row_component(Node(UNIT, 'u:games:steam:apt\\steam', 'steam', 2, [])) == 'steam'
    assert _row_component(Node(PROFILE, 'p:games', 'games', 0, [])) is None
    assert _row_component(None) is None


def test_pick_method_writes_pin_and_signals_reload(tmp_path, monkeypatch):
    cfgdir = _steam_home(tmp_path)
    ctx = _ctx(tmp_path)                                    # NOT --pretend: real write
    ms = _menu_on(ctx, 'steam')                            # steam has native + flatpak candidates
    monkeypatch.setattr(menu, 'suspended', lambda scr: contextlib.nullcontext())
    monkeypatch.setattr(builtins, 'input', lambda *a: '2')  # choose the 2nd method (flatpak)
    changed, note = menu._pick_method(None, ms, ctx)
    assert changed and 'flatpak' in note
    assert plugins.read_pins(str(cfgdir / 'configsys.hu')).get('steam') == 'flatpak'


def test_pick_method_cancel_writes_nothing(tmp_path, monkeypatch):
    cfgdir = _steam_home(tmp_path)
    ctx = _ctx(tmp_path)
    ms = _menu_on(ctx, 'steam')
    monkeypatch.setattr(menu, 'suspended', lambda scr: contextlib.nullcontext())
    monkeypatch.setattr(builtins, 'input', lambda *a: '')    # Enter = cancel
    changed, _note = menu._pick_method(None, ms, ctx)
    assert not changed
    assert plugins.read_pins(str(cfgdir / 'configsys.hu')) == {}


def test_pick_method_single_method_is_a_noop(tmp_path, monkeypatch):
    _steam_home(tmp_path)
    ctx = _ctx(tmp_path)
    ms = _menu_on(ctx, 'btop')                              # btop is native-only here
    monkeypatch.setattr(menu, 'suspended', lambda scr: contextlib.nullcontext())
    called = []
    monkeypatch.setattr(builtins, 'input', lambda *a: called.append(1) or '2')
    changed, note = menu._pick_method(None, ms, ctx)
    assert not changed and 'only one install method' in note
    assert not called                                       # never even prompted


def test_pick_method_pretend_does_not_write(tmp_path, monkeypatch):
    cfgdir = _steam_home(tmp_path)
    ctx = _ctx(tmp_path, '--pretend')
    ms = _menu_on(ctx, 'steam')
    monkeypatch.setattr(menu, 'suspended', lambda scr: contextlib.nullcontext())
    monkeypatch.setattr(builtins, 'input', lambda *a: '2')
    changed, note = menu._pick_method(None, ms, ctx)
    assert not changed and '[pretend]' in note
    assert plugins.read_pins(str(cfgdir / 'configsys.hu')) == {}
