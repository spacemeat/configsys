'''The primary's git layer is safe off the happy path (docs/todo/primary-safety-plan.md; findings in
docs/review-2026-11/primary.md): the ambient git environment never redirects it, file names that aren't
UTF-8 and very long path lists don't crash the snapshot/commit bracket, paths are never globs, and the
non-interactive network env keeps your own ssh command.'''

import os
import shutil
import subprocess

import pytest

from configsys import primarygit

from test_primary_push import BASE_P, _ctx, _git, primary  # noqa: F401

needs_git = pytest.mark.skipif(shutil.which('git') is None, reason='git not available')


def _log(repo):
    return _git(repo, 'log', '--format=%s')


@needs_git
def test_an_ambient_git_dir_never_redirects_the_primary(primary, tmp_path, monkeypatch):
    # inside `yadm enter` / `vcsh enter`, GIT_DIR + GIT_WORK_TREE point at your dotfiles repo; the
    # primary's snapshot / commit / state must still act on the primary (review primary-06)
    base, clone, bare, other = primary
    dot = tmp_path / 'dotfiles'
    subprocess.run(['git', 'init', '-q', str(dot)], check=True)
    (dot / 'secret.txt').write_text('token')
    monkeypatch.setenv('GIT_DIR', str(dot / '.git'))
    monkeypatch.setenv('GIT_WORK_TREE', str(dot))
    ctx = _ctx(base)
    snap = primarygit.snapshot(ctx)
    assert snap is not None and snap.dirty == set()
    (clone / 'p.hu').write_text(BASE_P.replace('[ btop ]', '[ btop  fzf ]'))
    assert primarygit.commit(ctx, snap, 'picks add fzf') == []
    st = primarygit.state(ctx)
    monkeypatch.delenv('GIT_DIR')
    monkeypatch.delenv('GIT_WORK_TREE')
    assert _log(clone).splitlines()[0] == 'picks add fzf'
    assert subprocess.run(['git', 'log'], cwd=dot, capture_output=True).returncode != 0   # nothing there
    assert st['branch'] == 'main' and st['ahead'] == 1


@needs_git
def test_a_file_name_that_is_not_utf8_does_not_break_the_bracket(primary):
    # an app writing into a config dir that's linked into the primary can create one (primary-05)
    base, clone, bare, other = primary
    odd = os.fsencode(str(clone / 'dotfiles')) + b'/caf\xe9.conf'
    os.makedirs(clone / 'dotfiles')
    with open(odd, 'wb') as fh:
        fh.write(b'x')
    ctx = _ctx(base)
    snap = primarygit.snapshot(ctx)
    assert snap is not None and len(snap.dirty) == 1               # the odd name, already dirty
    (clone / 'p.hu').write_text(BASE_P.replace('[ btop ]', '[ btop  fzf ]'))
    assert primarygit.commit(ctx, snap, 'picks add fzf') == []
    assert _log(clone).splitlines()[0] == 'picks add fzf'
    assert os.path.exists(odd)                                     # left alone, still uncommitted
    assert primarygit.state(ctx)['dirty'] is True


@needs_git
def test_a_long_path_list_commits_without_overflowing_the_command_line(primary):
    # a `dotfiles capture` of a big config dir: thousands of paths at once (primary-05)
    base, clone, bare, other = primary
    ctx = _ctx(base)
    snap = primarygit.snapshot(ctx)
    cfs = clone / 'dotfiles' / 'big-dotfiles.cfs' / 'a-rather-long-directory-name-for-the-config'
    cfs.mkdir(parents=True)
    for i in range(2000):
        (cfs / f'theme-file-number-{i:05d}.conf').write_text(str(i))
    assert primarygit.commit(ctx, snap, 'dotfiles capture big-dotfiles') == []
    assert _git(clone, 'status', '--porcelain') == ''
    assert _git(clone, 'show', '--stat', '--format=%s', 'HEAD').splitlines()[0] == \
        'dotfiles capture big-dotfiles'


@needs_git
def test_paths_are_literal_never_globs(primary):
    # a captured `a[bc].conf` must not stage your hand-edited `ab.conf` (primary-18)
    base, clone, bare, other = primary
    (clone / 'ab.conf').write_text('mine\n')
    _git(clone, 'add', 'ab.conf')
    _git(clone, 'commit', '-qm', 'ab')
    (clone / 'ab.conf').write_text('mine, edited by hand\n')
    ctx = _ctx(base)
    snap = primarygit.snapshot(ctx)
    (clone / 'a[bc].conf').write_text('captured\n')
    primarygit.commit(ctx, snap, 'capture')
    assert _git(clone, 'status', '--porcelain', 'ab.conf') == 'M ab.conf'   # still unstaged (" M")


@needs_git
def test_the_non_interactive_network_env_keeps_your_ssh_command(primary, monkeypatch):
    # push and the background fetch never prompt — and never replace your core.sshCommand (primary-10)
    base, clone, bare, other = primary
    repo = primarygit.PrimaryRepo(clone)
    monkeypatch.delenv('GIT_SSH_COMMAND', raising=False)
    assert repo.network_env(interactive=False)['GIT_SSH_COMMAND'] == 'ssh -o BatchMode=yes'
    _git(clone, 'config', 'core.sshCommand', 'ssh -i ~/.ssh/primary_key')
    env = repo.network_env(interactive=False)
    assert env['GIT_SSH_COMMAND'] == 'ssh -i ~/.ssh/primary_key -o BatchMode=yes'
    assert env['GIT_TERMINAL_PROMPT'] == '0'
    monkeypatch.setenv('GIT_SSH_COMMAND', 'ssh -F /tmp/cfg')
    assert repo.network_env(interactive=False)['GIT_SSH_COMMAND'] == 'ssh -F /tmp/cfg -o BatchMode=yes'
    assert 'GIT_TERMINAL_PROMPT' not in repo.network_env(interactive=True)


@needs_git
def test_the_bracket_never_raises(primary, monkeypatch):
    # snapshot / commit / state are best-effort: a git that can't run is "nothing to do", not a crash
    base, clone, bare, other = primary
    ctx = _ctx(base)
    snap = primarygit.snapshot(ctx)

    def boom(*a, **k):
        raise OSError('git vanished')
    monkeypatch.setattr(primarygit.PrimaryRepo, 'git', boom)
    assert primarygit.snapshot(ctx) is None
    assert primarygit.state(ctx) is None
    notes = primarygit.commit(ctx, snap, 'x')
    assert notes and 'could not' in notes[0]
