'''Primary-push plan, phase 1 (docs/done/primary-push-plan.md): configsys commits its own edits to
the primary plugin, locally, with a message saying what it did — and never sweeps in edits you were
making by hand.'''

import shutil

import pytest

from configsys import primarygit
from configsys.app import main

from fakes import git as _git, primary_remote

pytestmark = [pytest.mark.real_runner, pytest.mark.skipif(shutil.which('git') is None, reason='git not available')]


@pytest.fixture
def primary(tmp_path):
    '''A sandbox home whose blessed primary `prim` is cloned from a bare remote; git identity is the
    test's own (conftest's `_hermetic`), so commits never depend on the developer's ~/.gitconfig.'''
    base, clone, _bare, _seed = primary_remote(tmp_path, {'p.hu': '{ picks: { this-machine: [ btop ] } }\n'})
    return base, clone


def _log(clone):
    return _git(clone, 'log', '--format=%s', '-n', '5').splitlines()


def test_a_cli_edit_is_committed_with_the_command_as_message(primary, capsys):
    base, clone = primary
    assert main(base + ['picks', 'add', 'fzf']) == 0
    assert _log(clone)[0] == 'picks add fzf'
    assert 'fzf' in _git(clone, 'show', 'HEAD:p.hu')
    assert 'Made by configsys' in _git(clone, 'log', '-1', '--format=%b')
    assert _git(clone, 'status', '--porcelain') == ''


def test_global_flags_stay_out_of_the_message_but_machine_is_kept():
    from configsys.app import _command_words
    assert _command_words(['--home', '/h', '--os', 'pop', '-q', 'picks', 'add', 'fzf'], 'picks') == 'picks add fzf'
    assert (_command_words(['--machine', 'laptop', 'config', 'set', 'splash', 'plain'], 'config')
            == 'config set splash plain (machine laptop)')


def test_hand_edits_are_never_swept_in(primary, capsys):
    base, clone = primary
    (clone / 'plugin.hu').write_text('{ name: prim  requires-abi: 1  data: [ p.hu ]  mine: 1 }\n')
    assert main(base + ['picks', 'add', 'fzf']) == 0
    assert _log(clone)[0] == 'picks add fzf'
    assert _git(clone, 'show', '--name-only', '--format=', 'HEAD') == 'p.hu'   # only what configsys wrote
    assert _git(clone, 'status', '--porcelain') == 'M plugin.hu'              # yours, still uncommitted


def test_a_file_you_were_editing_is_left_for_you(primary, capsys):
    base, clone = primary
    (clone / 'p.hu').write_text('{ picks: { this-machine: [ btop ] } }\n// my note\n')
    capsys.readouterr()
    assert main(base + ['picks', 'add', 'fzf']) == 0
    assert _log(clone) == ['A']                                               # nothing committed
    assert 'also has edits of your own' in capsys.readouterr().out
    text = (clone / 'p.hu').read_text()
    assert 'fzf' in text and 'my note' in text


def test_pretend_commits_nothing(primary):
    base, clone = primary
    main(base + ['--pretend', 'picks', 'add', 'fzf'])
    assert _log(clone) == ['A']


def test_a_tag_pinned_primary_is_not_committed_to(primary, capsys):
    base, clone = primary
    _git(clone, 'checkout', '-q', '--detach')
    capsys.readouterr()
    assert main(base + ['picks', 'add', 'fzf']) == 0
    assert _log(clone) == ['A']
    assert 'did not commit' in capsys.readouterr().out


def _no_identity(monkeypatch, tmp_path, clone):
    for k in ('GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL', 'EMAIL'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv('HOME', str(tmp_path / 'nohome'))              # no ~/.gitconfig
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'nohome' / '.config'))
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    _git(clone, 'config', 'user.useConfigOnly', 'true')              # no auto-detected login@host


def test_missing_identity_commits_nothing_and_says_so(primary, monkeypatch, tmp_path, capsys):
    # review-2026-11 B19 (decision 4): configsys never invents `<login>@<host>` as your identity
    base, clone = primary
    _no_identity(monkeypatch, tmp_path, clone)
    capsys.readouterr()
    assert main(base + ['picks', 'add', 'fzf']) == 0
    assert _log(clone) == ['A']
    assert 'no git identity is set' in capsys.readouterr().out
    assert _git(clone, 'status', '--porcelain')                         # the edit is still here


def test_an_identity_from_the_environment_counts(primary, monkeypatch, tmp_path, capsys):
    # B15 / primary-24: GIT_AUTHOR_* / GIT_COMMITTER_* with no git config is an identity
    base, clone = primary
    _no_identity(monkeypatch, tmp_path, clone)
    for k, v in (('GIT_AUTHOR_NAME', 'e'), ('GIT_AUTHOR_EMAIL', 'e@x'), ('GIT_COMMITTER_NAME', 'e'),
                 ('GIT_COMMITTER_EMAIL', 'e@x')):
        monkeypatch.setenv(k, v)
    capsys.readouterr()
    assert main(base + ['picks', 'add', 'fzf']) == 0
    assert _log(clone)[0] == 'picks add fzf'
    assert 'no git identity' not in capsys.readouterr().out
    assert _git(clone, 'log', '-1', '--format=%an <%ae>') == 'e <e@x>'


def test_the_commit_body_names_the_configsys_machine_not_the_host(primary):
    import socket
    base, clone = primary
    assert main(base + ['machine', 'use', 'desk']) == 0
    assert main(base + ['picks', 'add', 'fzf']) == 0
    body = _git(clone, 'log', '-1', '--format=%b')
    assert body == 'Made by configsys on desk.' and socket.gethostname() not in body


def test_the_tui_bracket_commits_one_action(primary):
    from configsys.app import Context, build_parser
    from configsys.tui import menu
    base, clone = primary
    ctx = Context(build_parser().parse_args(base + ['inspect']))
    snap = primarygit.snapshot(ctx)
    primarygit.will_write(clone / 'p.hu')
    (clone / 'p.hu').write_text('{ picks: { this-machine: [ btop  jq ] } }\n')   # what a toggle writes
    assert menu._commit_primary_action(ctx, snap, 'profiles', 'track-one', 'tracking jq') == []
    assert _log(clone)[0] == 'profiles: toggle tracking: highlighted — tracking jq'


def test_configsys_own_commits_skip_your_hooks(primary):
    # decision 1: a global pre-commit hook must not run (or fail) on every TUI write; signing is
    # left to your setting
    from configsys.app import Context, build_parser
    base, clone = primary
    hook = clone / '.git' / 'hooks' / 'pre-commit'
    hook.write_text('#!/bin/sh\necho hook ran >&2\nexit 1\n')
    hook.chmod(0o755)
    ctx = Context(build_parser().parse_args(base + ['inspect']))
    snap = primarygit.snapshot(ctx)
    primarygit.will_write(clone / 'p.hu')
    (clone / 'p.hu').write_text('{ picks: { this-machine: [ btop  jq ] } }\n')
    assert primarygit.commit(ctx, snap, 'picks add jq') == []
    assert _log(clone)[0] == 'picks add jq'
