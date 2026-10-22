'''Primary-push plan, phase 1 (docs/done/primary-push-plan.md): configsys commits its own edits to
the primary plugin, locally, with a message saying what it did — and never sweeps in edits you were
making by hand.'''

import shutil
import subprocess

import pytest

from configsys import primarygit
from configsys.app import main

pytestmark = pytest.mark.skipif(shutil.which('git') is None, reason='git not available')


def _git(cwd, *a):
    return subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def primary(tmp_path, monkeypatch):
    '''A sandbox home whose blessed primary `prim` is cloned from a bare remote; git identity is the
    test's own (GIT_* env), so commits never depend on the developer's ~/.gitconfig.'''
    for k, v in (('GIT_AUTHOR_NAME', 't'), ('GIT_AUTHOR_EMAIL', 't@t'), ('GIT_COMMITTER_NAME', 't'),
                 ('GIT_COMMITTER_EMAIL', 't@t')):
        monkeypatch.setenv(k, v)
    bare = tmp_path / 'prim'
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(bare)], check=True)
    seed = tmp_path / 'seed'
    subprocess.run(['git', 'clone', '-q', str(bare), str(seed)], check=True, capture_output=True)
    (seed / 'plugin.hu').write_text('{ name: prim  requires-abi: 1  data: [ p.hu ] }\n')
    (seed / 'p.hu').write_text('{ picks: { this-machine: [ btop ] } }\n')
    _git(seed, 'add', '-A'); _git(seed, 'commit', '-qm', 'A'); _git(seed, 'push', '-q', 'origin', 'main')
    home = tmp_path / 'home'
    base = ['--home', str(home), '--os', 'pop', '-q']
    assert main(base + ['plugin', 'bless', str(bare)]) == 0
    clone = home / '.config' / 'configsys' / 'plugins' / 'prim'
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


def test_missing_identity_falls_back_and_says_so(primary, monkeypatch, tmp_path, capsys):
    base, clone = primary
    for k in ('GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL'):
        monkeypatch.delenv(k)
    monkeypatch.setenv('HOME', str(tmp_path / 'nohome'))              # no ~/.gitconfig
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'nohome' / '.config'))
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    capsys.readouterr()
    assert main(base + ['picks', 'add', 'fzf']) == 0
    assert _log(clone)[0] == 'picks add fzf'
    assert 'no git identity is set' in capsys.readouterr().out


def test_the_tui_bracket_commits_one_action(primary):
    from configsys.app import Context, build_parser
    from configsys.tui import menu
    base, clone = primary
    ctx = Context(build_parser().parse_args(base + ['inspect']))
    snap = primarygit.snapshot(ctx)
    (clone / 'p.hu').write_text('{ picks: { this-machine: [ btop  jq ] } }\n')   # what a toggle writes
    assert menu._commit_primary_action(ctx, snap, 'profiles', 'track-one', 'tracking jq') == []
    assert _log(clone)[0] == 'profiles: toggle tracking: highlighted — tracking jq'
