'''Failed ops stay on the ! page until fixed, with the line that says WHY; and a TUI batch refreshes
the package index once, up front — never again between System Updates and the component ops.'''

import builtins
import contextlib
from types import SimpleNamespace

import configsys.app as app
from configsys.cli import refresh as cli_refresh
from configsys import reportgen
from configsys.actions import failure_excerpt
from configsys.ledger import Ledger
from configsys.tui import menu
from configsys.tui import flows as flows_mod

from test_execute import FakeRunner, ctx_for, unit


# -- the WHY line -----------------------------------------------------------

_GO = '''go: downloading github.com/ayn2op/discordo v0.0.0-20261020010606-2c8d24d94015
go: github.com/ayn2op/discordo@latest (in github.com/ayn2op/discordo@v0.0.0-20261020010606-2c8d24d94015):
\tThe go.mod file for the module providing named packages contains one or
\tmore replace directives. It must not contain directives that would cause
\tit to be interpreted differently than if it were the main module.'''

_PIP = '''error: externally-managed-environment

× This environment is externally managed
╰─> To install Python packages system-wide, try apt install
    python3-xyz, where xyz is the package you are trying to

hint: See PEP 668 for the detailed specification.'''


def test_excerpt_prefers_the_error_line_over_a_trailing_hint():
    assert failure_excerpt(_PIP) == 'error: externally-managed-environment'
    assert failure_excerpt('E: Unable to locate package foo') == 'E: Unable to locate package foo'


def test_excerpt_takes_a_wrapped_trailing_paragraph_whole():
    got = failure_excerpt(_GO, limit=1000)
    assert got.startswith('go: github.com/ayn2op/discordo@latest')
    assert 'more replace directives' in got and got.endswith('the main module.')


def test_excerpt_truncates():
    assert len(failure_excerpt('x' * 500)) == 240


# -- unresolved failures across runs ---------------------------------------

def test_a_failure_persists_until_that_unit_succeeds(tmp_path):
    fr = FakeRunner(fail_substrings=['apt-get install -y btop'])
    ctx = ctx_for(tmp_path, fr)
    menu.execute_plan(ctx, [('install', 'apt\\btop', unit('btop'))], Ledger())
    assert [f['unit'] for f in reportgen.load_failures(ctx.paths)] == ['apt\\btop']
    # an unrelated, clean run leaves it alone (it used to survive only until the next failing run)
    menu.execute_plan(ctx, [('install', 'apt\\fzf', unit('fzf'))], Ledger())
    assert [f['unit'] for f in reportgen.load_failures(ctx.paths)] == ['apt\\btop']
    # a different failure joins it rather than replacing it
    fr.fail = ('apt-get install -y btop', 'apt-get install -y jq')
    menu.execute_plan(ctx, [('install', 'apt\\jq', unit('jq'))], Ledger())
    assert sorted(f['unit'] for f in reportgen.load_failures(ctx.paths)) == ['apt\\btop', 'apt\\jq']
    # btop finally installs -> its record goes
    fr.fail = ('apt-get install -y jq',)
    menu.execute_plan(ctx, [('install', 'apt\\btop', unit('btop'))], Ledger())
    assert [f['unit'] for f in reportgen.load_failures(ctx.paths)] == ['apt\\jq']


def test_pretend_records_nothing(tmp_path):
    fr = FakeRunner(fail_substrings=['btop'])
    fr.pretend = True
    ctx = ctx_for(tmp_path, fr)
    menu.execute_plan(ctx, [('install', 'apt\\btop', unit('btop'))], Ledger())
    assert not ctx.paths.failure_file.exists()


def _rec(unit_key, op, output='E: boom'):
    return {'component': unit_key.split('\\')[-1], 'unit': unit_key, 'driver': 'apt', 'op': op,
            'command': 'x', 'exit': 1, 'output': output, 'at': '2026-10-20 23:41:25'}


def _st(present, outdated=False):
    return SimpleNamespace(present=present, outdated=outdated)


def test_failure_issue_text_names_op_when_why_and_fix(tmp_path):
    ctx = ctx_for(tmp_path, FakeRunner())
    reportgen.save_failures(ctx.paths, [_rec('go-install\\discordo', 'upgrade', _GO)])
    (text,) = app._failure_diagnostics(ctx, None)
    assert text.startswith('go-install\\discordo: upgrade failed 2026-10-20 23:41:25 (exit 1)')
    assert 'replace directives' in text
    assert text.endswith('configsys report discordo')


def test_moot_failures_are_hidden():
    open_ = app._failure_open
    assert open_(_rec('apt\\a', 'install'), {'apt\\a': _st(False)})
    assert not open_(_rec('apt\\a', 'install'), {'apt\\a': _st(True)})          # installed since
    assert open_(_rec('apt\\a', 'upgrade'), {'apt\\a': _st(True, outdated=True)})
    assert not open_(_rec('apt\\a', 'upgrade'), {'apt\\a': _st(True)})          # current now
    assert open_(_rec('apt\\a', 'remove'), {'apt\\a': _st(True)})
    assert not open_(_rec('apt\\a', 'remove'), {'apt\\a': _st(False)})          # gone now
    assert not open_(_rec('apt\\a', 'install'), {})                              # pick dropped
    assert open_(_rec('system-updates\\apt', 'upgrade'), {})                     # bulk: always
    assert open_(_rec('apt\\a', 'install'), None)                                # nothing inspected


def test_installed_with_a_warning_is_not_an_issue(tmp_path):
    ctx = ctx_for(tmp_path, FakeRunner())
    rec = dict(_rec('apt\\a', 'install'), installed='true')
    reportgen.save_failures(ctx.paths, [rec])
    assert app._failure_diagnostics(ctx, None) == []


# -- one refresh per TUI batch ----------------------------------------------

def _su_state():
    comp = SimpleNamespace(fields={'system_update': True}, driver='apt', name='nano', key='su\\nano')
    return SimpleNamespace(component=comp, present=True)


def test_tui_batch_refreshes_once_up_front(monkeypatch, tmp_path, capsys):
    import configsys.installState as installState
    from configsys import sysupdates
    seen = []
    ctx = ctx_for(tmp_path, FakeRunner())
    rc = unit('tmux')
    ms = SimpleNamespace(
        plan=lambda: [('upgrade', 'su\\nano', _su_state().component), ('upgrade', 'apt\\tmux', rc)],
        states={'su\\nano': _su_state(), 'apt\\tmux': SimpleNamespace(component=rc, present=True)})
    monkeypatch.setattr(flows_mod, 'suspended', lambda scr: contextlib.nullcontext())
    monkeypatch.setattr(builtins, 'input', lambda *a: 'y')
    monkeypatch.setattr(installState, 'plan_with_swaps', lambda c, raw, units: (raw, units))
    monkeypatch.setattr(cli_refresh, 'maybe_refresh_before_plan',
                        lambda c, plan, system=False: seen.append(('refresh', system)) or {'tmux', 'nano'})
    monkeypatch.setattr(sysupdates, 'apply_bulk', lambda c, mgrs, refresh=True: (
        seen.append(('bulk', refresh)) or [(m, SimpleNamespace(ok=True)) for m in mgrs]))
    monkeypatch.setattr(flows_mod, 'execute_plan', lambda c, plan, led, refresh=True, version=None: (
        seen.append(('plan', refresh)) or []))
    monkeypatch.setattr(cli_refresh, 'published_pending', lambda c, fresh: sorted(fresh))
    menu._confirm_and_execute(None, None, ms, ctx, Ledger())
    assert seen == [('refresh', True), ('bulk', False), ('plan', False)]
    out = capsys.readouterr().out
    assert 'Published since you staged' in out and 'nano, tmux' in out


def _refresh_ctx(lists):
    '''A ctx whose `apt list --upgradable` answers successive entries of `lists`.'''
    from configsys.runner import Result
    calls = []

    class R:
        pretend = False

        def run(self, cmd, *, sudo=False, capture=True, **kw):
            calls.append(cmd)
            if cmd.startswith('apt list --upgradable'):
                names = lists.pop(0) if lists else []
                return Result(cmd, 0, stdout='Listing...\n' + ''.join(
                    f'{n}/jammy-updates 2 amd64 [upgradable from: 1]\n' for n in names))
            return Result(cmd, 0)
    ctx = SimpleNamespace(config=SimpleNamespace(refresh_before_execute=lambda: 'never'),
                          routes=SimpleNamespace(cascade=SimpleNamespace(native=lambda b: 'apt')),
                          os_info=SimpleNamespace(block='pop'), runner=R(), paths=None)
    return ctx, calls


def test_refresh_reports_what_it_newly_made_upgradable():
    # system=True refreshes even under `never` (the bulk upgrade always read a fresh index)
    ctx, calls = _refresh_ctx([['nano'], ['nano', 'tmux']])
    fresh = app.maybe_refresh_before_plan(ctx, [], system=True)
    assert any('apt-get update' in c for c in calls)
    assert fresh == {'tmux'}


def test_published_pending_keeps_only_what_the_batch_left():
    ctx, _calls = _refresh_ctx([['tmux', 'ubuntu-pro-client']])
    assert app.published_pending(ctx, {'tmux', 'nano'}) == ['tmux']
    assert app.published_pending(ctx, set()) == []
