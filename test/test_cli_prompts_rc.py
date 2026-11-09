'''The CLI's prompts and exit codes (review-2026-11-2 app-cli-18/23/26/28/30/32/34): one y/N policy
(`cli.common.ask`), exit codes that don't claim more than happened, `fix-scope` previewed and
confirmed, the `gh` body tempfile removed, a closed pipe exiting quietly, no first-run primary offer
outside the TUI, and `--pretend plugin list --fetch` not reporting a failed fetch.'''

import argparse
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from configsys import actions, primarygit
from configsys.app import Context, main
from configsys.cli import common, issues, ops, plugin as cli_plugin, refresh, settings
from configsys.runner import Result


def _no_input(*_a, **_k):
    raise AssertionError('input() must not be called here')


def _tty(monkeypatch, on):
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: on, raising=False)
    monkeypatch.setattr(sys.stdout, 'isatty', lambda: on, raising=False)


# -- app-cli-18: the one prompt ---------------------------------------------

def test_ask_policy(monkeypatch, capsys):
    monkeypatch.setattr('builtins.input', _no_input)
    assert common.ask('go? ', yes=True) is True
    assert common.ask('go? ', pretend=True) is False
    assert '[pretend] would ask: go?' in capsys.readouterr().out
    _tty(monkeypatch, False)
    assert common.ask('go? ', refuse_note='need --yes') is None          # refused: falsy, distinct
    assert 'need --yes' in capsys.readouterr().out
    assert common.ask('go? ', noninteractive='no') is False
    assert capsys.readouterr().out == ''
    _tty(monkeypatch, True)
    monkeypatch.setattr('builtins.input', lambda _p: 'yes')
    assert common.ask('go? ') is True
    monkeypatch.setattr('builtins.input', lambda _p: '')
    assert common.ask('go? ') is False

    def eof(_p):
        raise EOFError
    monkeypatch.setattr('builtins.input', eof)
    assert common.ask('go? ') is False


def test_dotfiles_capture_without_a_terminal_refuses_cleanly(tmp_path, monkeypatch, capsys):
    base = ['--home', str(tmp_path), '--os', 'pop_os!:22.04', '-q']
    assert main(base + ['picks', 'add', 'btop']) == 0
    (tmp_path / '.config' / 'btop').mkdir(parents=True)
    (tmp_path / '.config' / 'btop' / 'btop.conf').write_text('color_theme = "x"\n')
    capsys.readouterr()
    _tty(monkeypatch, False)
    monkeypatch.setattr('builtins.input', _no_input)               # was an EOFError traceback
    assert main(base + ['dotfiles', 'capture', 'btop']) == 1
    out = capsys.readouterr().out
    assert 'will capture' in out and 're-run with --yes' in out


def test_plugin_undo_on_a_pipe_does_not_proceed(monkeypatch, capsys):
    asked = []

    def fake_undo(_ctx, confirm):
        change = SimpleNamespace(machine=None, short='abc1234', subject='pin set', pushed=False,
                                 files=['p.hu'])
        asked.append(confirm(change))
        return False, ['nothing undone']
    monkeypatch.setattr(primarygit, 'undo', fake_undo)
    monkeypatch.setattr('builtins.input', _no_input)
    _tty(monkeypatch, False)
    ctx = SimpleNamespace(runner=SimpleNamespace(pretend=False))
    assert cli_plugin._plugin_undo(ctx, argparse.Namespace(yes=False)) == 1
    assert asked == [False]                           # a pipe isn't consent (it used to say yes)
    assert cli_plugin._plugin_undo(ctx, argparse.Namespace(yes=True)) == 1
    assert asked == [False, True]


def _refresh_ctx(pm, *, pretend, runner=None, paths=None):
    native = SimpleNamespace(native=lambda _b: pm)
    return SimpleNamespace(
        load_pipeline=lambda: (None, [], {}, None, {}),
        routes=SimpleNamespace(cascade=native, components={}),
        os_info=SimpleNamespace(block='x'), paths=paths, config=None,
        runner=runner or SimpleNamespace(pretend=pretend, run=lambda *a, **k: Result('x', 0)))


def test_pretend_refresh_on_pacman_never_prompts(monkeypatch, capsys):
    monkeypatch.setattr('builtins.input', _no_input)
    _tty(monkeypatch, True)
    refresh.cmd_refresh(_refresh_ctx('pacman', pretend=True))
    out = capsys.readouterr().out
    assert '[pretend] would ask: Run `pacman -Syu --noconfirm` now' in out


# -- app-cli-23: exit codes and messages ------------------------------------

def test_refresh_exits_nonzero_when_the_index_refresh_failed(tmp_path, monkeypatch, capsys):
    paths = SimpleNamespace(state_dir=tmp_path)
    monkeypatch.setattr(refresh, '_installed_owners', lambda _c: set())
    monkeypatch.setattr(refresh, '_reconcile_managed_sources', lambda *a, **k: 0)
    monkeypatch.setattr('configsys.failures.retry_transient', lambda fn: fn())
    monkeypatch.setattr('configsys.refreshstate.record_stale_pins', lambda *a: None)
    bad = SimpleNamespace(pretend=False, run=lambda *a, **k: Result('apt-get update', 100, stderr='E: x'))
    assert refresh.cmd_refresh(_refresh_ctx('apt', pretend=False, runner=bad, paths=paths)) == 1
    good = SimpleNamespace(pretend=False, run=lambda *a, **k: Result('apt-get update', 0))
    monkeypatch.setattr('configsys.refreshstate.record', lambda _p: None)
    assert refresh.cmd_refresh(_refresh_ctx('apt', pretend=False, runner=good, paths=paths)) == 0
    capsys.readouterr()


def test_plugin_untrust_and_unbless_fail_honestly(tmp_path, capsys):
    base = ['--home', str(tmp_path), '--os', 'pop', '-q']
    assert main(base + ['plugin', 'untrust', 'nosuch']) == 1
    assert main(base + ['plugin', 'unbless']) == 1
    out = capsys.readouterr().out
    assert 'nosuch was not trusted' in out and 'no primary plugin set' in out


def test_config_unset_says_when_another_layer_still_sets_it(tmp_path, capsys):
    from test_config_move import _ctx_with_primary
    ctx, user, _prim = _ctx_with_primary(tmp_path)
    ctx.runner = SimpleNamespace(pretend=False)
    ctx.ensure_user_config = lambda: None
    actions.set_config_setting(ctx, 'splash', ['plain'])                         # -> the primary
    actions.set_config_setting(ctx, 'splash', ['braille-bar'], target=str(user))  # -> local, shadowing
    args = argparse.Namespace(config_command='unset', key='splash', value=[], local=False)
    assert settings.cmd_config(ctx, args) == 0
    cap = capsys.readouterr()
    assert 'cleared splash  (in top config)' in cap.out
    assert 'still set in myprim (= plain)' in cap.err
    assert settings.cmd_config(ctx, args) == 0                                   # now clears the primary's
    cap = capsys.readouterr()
    assert 'cleared splash  (in myprim)' in cap.out and 'still set' not in cap.err


# -- app-cli-26: fix-scope previews and confirms ------------------------------

def _fix_scope_ctx(monkeypatch, ran):
    rc = SimpleNamespace(comp='btop', driver='fake', key='fake\\btop')
    st = SimpleNamespace(component=rc, present=True, scope='user')
    monkeypatch.setattr(ops, 'get_driver', lambda *a, **k: SimpleNamespace(
        honors_scope=True, scope=lambda _rc: 'system'))
    monkeypatch.setattr(actions, 'run_plan', lambda c, plan, ledger=None: (
        ran.append(plan) or SimpleNamespace(failures=[], n_fatal=0, rc_code=0)))
    return SimpleNamespace(runner=SimpleNamespace(pretend=False), paths=None,
                           load_pipeline=lambda: (None, [], {}, None, {'fake\\btop': st}))


def test_fix_scope_without_a_terminal_runs_nothing(monkeypatch, capsys):
    ran = []
    ctx = _fix_scope_ctx(monkeypatch, ran)
    _tty(monkeypatch, False)
    monkeypatch.setattr('builtins.input', _no_input)
    assert ops.cmd_fix_scope(ctx, argparse.Namespace(names=[], yes=False)) == 1
    assert ran == []
    out = capsys.readouterr().out
    assert 'fake\\btop: installed at user scope -> declared system' in out and '--yes' in out
    assert ops.cmd_fix_scope(ctx, argparse.Namespace(names=[], yes=True)) == 0
    assert [[(op, key) for op, key, _rc in plan] for plan in ran] == [[('fix-scope', 'fake\\btop')]]


# -- app-cli-28: the gh body tempfile ----------------------------------------

@pytest.mark.parametrize('code', [0, 1])
def test_gh_body_tempfile_is_removed(tmp_path, monkeypatch, code):
    import shutil
    seen = []

    def fake_run(argv, **_k):
        seen.append(argv[argv.index('--body-file') + 1])
        assert os.path.exists(seen[-1])                   # there while gh reads it
        return subprocess.CompletedProcess(argv, code, stdout='https://x/1\n', stderr='nope')
    monkeypatch.setattr(shutil, 'which', lambda n, *a, **k: '/usr/bin/gh' if n == 'gh' else None)
    monkeypatch.setattr(subprocess, 'run', fake_run)
    ctx = SimpleNamespace(runner=SimpleNamespace(pretend=False), paths=SimpleNamespace(state_dir=tmp_path))
    rc = issues._file_issue(ctx, "title", "scrubbed body").rc
    assert rc == 0 and seen and not os.path.exists(seen[0])


# -- app-cli-30: a closed pipe ------------------------------------------------

class _ClosedPipe:
    encoding = 'utf-8'

    def write(self, _s):
        raise BrokenPipeError(32, 'Broken pipe')

    def flush(self):
        raise BrokenPipeError(32, 'Broken pipe')

    def isatty(self):
        return False


def test_a_closed_pipe_exits_quietly(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'stdout', _ClosedPipe())
    assert main(['--home', str(tmp_path), '--os', 'pop', '--pretend', 'profile', 'list']) == 141


def test_piping_to_head_prints_no_broken_pipe_traceback(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CONFIGSYS_', 'XDG_'))}
    env['HOME'] = str(tmp_path)
    p = subprocess.Popen([sys.executable, '-m', 'configsys', '--home', str(tmp_path), '--os', 'pop',
                          '--pretend', 'profile', 'list'], cwd=os.path.dirname(os.path.dirname(
                              os.path.abspath(__file__))), env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p.stdout.readline()
    p.stdout.close()                                  # like `| head -1`
    err = p.stderr.read().decode()
    p.wait(timeout=60)
    assert 'BrokenPipeError' not in err


# -- app-cli-32: no first-run primary offer outside the TUI --------------------

def test_a_pipeline_command_never_offers_the_primary(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Context, '_offer_primary', lambda self: _no_input())
    assert main(['--home', str(tmp_path), '--os', 'pop', 'inspect']) == 0
    assert 'generated' in capsys.readouterr().out          # the first run DID generate the config


def test_cmd_refresh_takes_no_args_from_the_tui():
    import inspect
    assert inspect.signature(refresh.cmd_refresh).parameters['args'].default is None


# -- app-cli-34: --pretend plugin list --fetch ---------------------------------

def test_pretend_plugin_list_fetch_says_not_fetched(tmp_path, monkeypatch, capsys):
    from configsys import plugins
    row = {'name': 'myprim', 'source': 'github:me/myprim', 'ref': None, 'synced': True,
           'checksum': 'ok', 'abi_ok': True, 'code_state': None, 'primary': True, 'locked': None,
           'provisions': []}
    monkeypatch.setattr(plugins, 'status', lambda *a, **k: [row])
    monkeypatch.setattr(primarygit, 'fetch', lambda c: _no_input())
    monkeypatch.setattr(primarygit, 'state', lambda c: None)
    assert main(['--home', str(tmp_path), '--os', 'pop', '--pretend', 'plugin', 'list', '--fetch']) == 0
    out = capsys.readouterr().out
    assert '[pretend — not fetched]' in out and 'could not fetch' not in out
