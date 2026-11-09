'''TUI follow-ups from review-2026-11-2 parity-15/16/17: the `!` page's keys are a keymap scope
(rebindable, listed in `?`, legend from your bindings), the post-batch summary points at the in-TUI
path (and says nothing under --pretend), the System Updates confirm counts after the refresh, a Config
bool can be unset, Profiles `v` reaches provider-pins, and a Plugins sync says how the install set
moved.'''

import builtins
import contextlib
from types import SimpleNamespace

import pytest

from _render_harness import RecordingPalette, build_ctx
from configsys import actions, sysupdates
from configsys.actions import OpOutcome
from configsys.cli import refresh as cli_refresh, where
from configsys.ledger import Ledger
from configsys.tui import flows, keyspec, menu, modals
from configsys.tui.surface import BufferSurface

from test_execute import FakeRunner, ctx_for, unit


@pytest.fixture(scope='module')
def ctx(tmp_path_factory):
    return build_ctx(tmp_path_factory.mktemp('parity'))


def _shipped_keys():
    from configsys.layers import read_tree
    from configsys.paths import Paths
    return read_tree(Paths({}).config_file)[1]['keys']


# -- parity-15 ----------------------------------------------------------------

def test_issue_keys_are_a_keymap_scope_listed_in_help():
    km = keyspec.shipped_keymap()
    assert set(menu._ISSUE_KINDS) == keyspec.KNOWN_ACTIONS['issues']
    assert [km.action_for('issues', ord(c)) for c in 'rfs'] == ['report', 'request', 'suggest-os']
    labels = [lbl for _k, lbl in km.help_rows('issues')]
    assert keyspec.ACTION_LABELS['report'] in labels and keyspec.ACTION_LABELS['suggest-os'] in labels


def test_issues_footer_follows_a_rebind(monkeypatch):
    keys = dict(_shipped_keys())
    keys['issues'] = {'report': 'R', 'request': 'f', 'suggest-os': 's'}
    keys['global'] = {**keys['global'], 'down': 'J'}
    monkeypatch.setattr(menu, '_KEYMAP', keyspec.Keymap(keys))
    surf = BufferSurface(24, 160)
    modals._draw_diagnostics(surf, RecordingPalette(), [], 0)
    foot = surf.text_rows()[-1]
    assert 'R report a component' in foot and 'J/k scroll' in foot and 'r report' not in foot


def test_machines_modal_title_names_the_fan_out_keys():
    import inspect
    src = inspect.getsource(modals._machines_modal)
    assert 'A/D' not in src and 'track-all' in src


def _failing_batch(monkeypatch, ctx, *, pretend):
    ctx.runner.pretend = pretend
    rc = unit('tmux')
    ms = SimpleNamespace(plan=lambda: [('install', 'apt\\tmux', rc)],
                         states={'apt\\tmux': SimpleNamespace(component=rc, present=False)})
    monkeypatch.setattr(flows, 'suspended', lambda scr: contextlib.nullcontext())
    monkeypatch.setattr(builtins, 'input', lambda *a: 'y')
    tty = SimpleNamespace(isatty=lambda: True)      # the TUI's own terminal (cli.common.ask checks it)
    monkeypatch.setattr('configsys.cli.common.sys', SimpleNamespace(stdin=tty, stdout=tty))
    monkeypatch.setattr(actions, 'build_plan', lambda c, raw, units, states=None: (raw, units, []))
    monkeypatch.setattr(cli_refresh, 'maybe_refresh_before_plan', lambda c, plan, system=False: set())
    monkeypatch.setattr(flows, 'execute_plan', lambda c, plan, led, refresh=True, version=None: [
        OpOutcome('install', 'apt\\tmux', 'tmux', False, 'E: boom')])
    monkeypatch.setattr(actions, 'after_run', lambda *a: None)
    flows._confirm_and_execute(None, None, ms, ctx, Ledger())


def test_batch_summary_points_at_the_issues_page(monkeypatch, tmp_path, capsys):
    _failing_batch(monkeypatch, ctx_for(tmp_path, FakeRunner()), pretend=False)
    out = capsys.readouterr().out
    assert '! → r files the details' in out and '`configsys report`' not in out


def test_batch_summary_under_pretend_offers_no_report(monkeypatch, tmp_path, capsys):
    _failing_batch(monkeypatch, ctx_for(tmp_path, FakeRunner()), pretend=True)
    out = capsys.readouterr().out
    assert 'FAILED' in out and 'files the details' not in out


# -- parity-16 ----------------------------------------------------------------

def _su_state(name):
    comp = SimpleNamespace(fields={'system_update': True}, driver='apt', name=name, key=f'su\\{name}')
    return SimpleNamespace(component=comp, present=True)


def test_system_updates_confirm_counts_after_the_refresh(monkeypatch, tmp_path, capsys):
    seen, shown = [], []
    ctx = ctx_for(tmp_path, FakeRunner())
    states = {f'su\\{n}': _su_state(n) for n in ('nano', 'vim')}
    ms = SimpleNamespace(plan=lambda: [('upgrade', k, st.component) for k, st in states.items()],
                         states=states)
    monkeypatch.setattr(flows, 'suspended', lambda scr: contextlib.nullcontext())

    def answer(*_a):
        shown.append(capsys.readouterr().out)        # what was on screen when you were asked
        return 'n'
    monkeypatch.setattr(builtins, 'input', answer)
    monkeypatch.setattr(cli_refresh, 'maybe_refresh_before_plan',
                        lambda c, plan, system=False: seen.append(('refresh', system)) or {'curl'})
    monkeypatch.setattr(sysupdates, 'gather', lambda c, notes_out=None: {'apt': [
        sysupdates.UpdateRow('apt', n, '1', '2', False) for n in ('nano', 'vim', 'curl')]})
    flows._confirm_and_execute(None, None, ms, ctx, Ledger())
    assert seen == [('refresh', True)]                # once, and before the question
    assert '(3 package(s), 1 of them published since the scan)' in shown[0]


# -- parity-17 ----------------------------------------------------------------

def test_config_bool_can_be_unset(monkeypatch):
    from configsys.tui.screens import config as config_mod
    from configsys.tui.screens.config import ConfigScreen
    calls, offered = [], []
    model = SimpleNamespace(keys=['reboot-advice'], cur=0, reload=lambda: None, settings={
        'reboot-advice': {'kind': 'bool', 'value': False, 'home': 'local'}})
    scr = ConfigScreen.__new__(ConfigScreen)
    scr.model = model
    monkeypatch.setattr(config_mod, '_popup_choose',
                        lambda s, p, title, opts, cur: offered.append((opts, cur)) or 2)
    monkeypatch.setattr(actions, 'set_config_setting', lambda c, k, v, **kw: calls.append((k, v)) or (True, 'x'))
    km = menu._keymap()
    confirm = next(k for k in range(1, 256) if km.action_for('config', k) == 'confirm')
    intent = scr.handle(confirm, SimpleNamespace(runner=SimpleNamespace(pretend=False)), None, None)
    assert [o[0] for o in offered[0][0]] == ['true', 'false', 'unset'] and offered[0][1] == 1
    assert calls == [('reboot-advice', [])] and intent.note == 'reboot-advice unset'


def test_pick_resolution_offers_the_provider_axis(ctx, monkeypatch):
    got = []
    monkeypatch.setattr(flows, '_popup_choose', lambda s, p, title, opts, cur: got.append(opts) or None)
    monkeypatch.setattr(flows, '_pick_provider_cap',
                        lambda s, p, c, name, cap, provs: got.append(('provider', cap)) or (False, 'x', None))
    flows._pick_resolution(None, None, ctx, 'cudnn-9')
    labels = [lbl for opts in got if isinstance(opts, list) for lbl, _d in opts]
    assert ('provider', 'cuda-toolkit') in got or 'provider for cuda-toolkit' in labels


def test_profiles_method_key_uses_the_full_chooser(ctx, monkeypatch):
    from configsys.tui.screens import profiles as prof_mod
    from configsys.tui.screens.profiles import ProfilesScreen
    scr = ProfilesScreen(ctx, menu._sample_profiles_state(ctx))
    ps = scr.model
    ps.focus = 'right'
    vcat = ps.vcatalog()
    ps.rcur = vcat.index('cudnn-9') if 'cudnn-9' in vcat else 0
    called = []
    monkeypatch.setattr(prof_mod, '_pick_resolution',
                        lambda s, p, c, name: called.append(name) or (False, 'unchanged', None))
    km = menu._keymap()
    v = next(k for k in range(32, 127) if km.own_action('profiles', k) == 'method')
    scr.handle(v, ctx, None, None)
    assert called == [vcat[ps.rcur]]


def test_sync_delta_summary():
    cfg = SimpleNamespace(requested=lambda: ['a', 'b', 'c'])
    assert where.delta_summary({'a', 'd'}, cfg) == 'install set +2 / -1 (review on Components)'
    assert where.delta_summary({'a', 'b', 'c'}, cfg) == ''
    from configsys.tui.screens.plugins import _with_delta
    ctx = SimpleNamespace(config=cfg)
    assert _with_delta('synced x', {'a', 'b'}, ctx) == 'synced x · install set +1 / -0 (review on Components)'
    assert _with_delta('synced x', {'a', 'b', 'c'}, ctx) == 'synced x'
