'''`primary-verify: signed` (review-2026-11 G4): your primary takes in commits from its remote only
when each carries a good signature from a key you trust — so whoever can push to the primary's
repository can't get unsigned data, glue or code onto your machines. Signing here is SSH signing with
a throwaway key, trusted through an allowed-signers file in a sandbox global git config.'''

import shutil
import subprocess

import pytest

from configsys import plugins, primarygit
from configsys.app import Context, build_parser, main

pytestmark = [pytest.mark.real_runner,
              pytest.mark.skipif(shutil.which('git') is None or shutil.which('ssh-keygen') is None,
                                 reason='git and ssh-keygen needed')]


def _git(cwd, *a):
    return subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def signing(tmp_path, monkeypatch):
    '''A trusted signing key (git signs with -S) and a sandbox global git config that trusts it.'''
    key = tmp_path / 'key'
    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 't@t', '-f', str(key)], check=True)
    allowed = tmp_path / 'allowed_signers'
    allowed.write_text(f't@t {(tmp_path / "key.pub").read_text()}')
    gitconfig = tmp_path / 'gitconfig'
    gitconfig.write_text(f'[user]\n\tname = t\n\temail = t@t\n\tsigningkey = {key}\n'
                         f'[gpg]\n\tformat = ssh\n[gpg "ssh"]\n\tallowedSignersFile = {allowed}\n')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', str(gitconfig))
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    for k in ('GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL'):
        monkeypatch.delenv(k, raising=False)
    return key


def _seed(tmp_path, *, signed):
    bare = tmp_path / 'prim'
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(bare)], check=True)
    other = tmp_path / 'other'
    subprocess.run(['git', 'clone', '-q', str(bare), str(other)], check=True, capture_output=True)
    (other / 'plugin.hu').write_text('{ name: prim  requires-abi: 1  data: [ p.hu ] }\n')
    (other / 'p.hu').write_text('{ picks: { this-machine: [ btop ] } }\n')
    _git(other, 'add', '-A'); _git(other, 'commit', '-q', *(['-S'] if signed else []), '-m', 'A')
    _git(other, 'push', '-q', 'origin', 'main')
    return bare, other


def _other_pushes(other, text, *, signed):
    (other / 'p.hu').write_text(text)
    _git(other, 'commit', '-qa', *(['-S'] if signed else []), '-m', 'B')
    _git(other, 'push', '-q', 'origin', 'main')


def _home(tmp_path, verify=True):
    home = tmp_path / 'home'
    base = ['--home', str(home), '--os', 'pop', '-q']
    if verify:
        assert main(base + ['config', 'set', 'primary-verify', 'signed']) == 0
    return base, home / '.config' / 'configsys' / 'plugins' / 'prim'


def test_an_unsigned_primary_is_never_cloned(signing, tmp_path, capsys):
    bare, _other = _seed(tmp_path, signed=False)
    base, clone = _home(tmp_path)
    capsys.readouterr()
    main(base + ['plugin', 'bless', str(bare)])
    assert 'not synced — its newest commit has no good signature' in capsys.readouterr().out
    assert not clone.exists()


def test_a_signed_primary_syncs_and_an_unsigned_commit_is_held_back(signing, tmp_path, capsys):
    bare, other = _seed(tmp_path, signed=True)
    base, clone = _home(tmp_path)
    assert main(base + ['plugin', 'bless', str(bare)]) == 0
    assert (clone / 'p.hu').exists()
    head = _git(clone, 'rev-parse', 'HEAD')
    _other_pushes(other, '{ picks: { this-machine: [ btop  evil ] } }\n', signed=False)
    capsys.readouterr()
    main(base + ['plugin', 'sync'])
    assert 'commits without a good signature' in capsys.readouterr().out
    assert _git(clone, 'rev-parse', 'HEAD') == head and 'evil' not in (clone / 'p.hu').read_text()
    _git(other, 'commit', '-q', '--amend', '-S', '--no-edit'); _git(other, 'push', '-qf', 'origin', 'main')
    main(base + ['plugin', 'sync'])                                   # signed now: it comes in
    assert 'evil' in (clone / 'p.hu').read_text()


def test_push_wont_combine_with_unsigned_commits(signing, tmp_path, capsys):
    bare, other = _seed(tmp_path, signed=True)
    base, clone = _home(tmp_path)
    assert main(base + ['plugin', 'bless', str(bare)]) == 0
    _other_pushes(other, '{ picks: { this-machine: [ btop ]  laptop: [ evil ] } }\n', signed=False)
    assert main(base + ['picks', 'add', 'fzf']) == 0
    head = _git(clone, 'rev-parse', 'HEAD')
    ctx = Context(build_parser().parse_args(base + ['inspect']))
    ok, lines = primarygit.push(ctx)
    assert not ok and 'without a good signature' in lines[-1] and 'B' in lines[-1]
    assert _git(clone, 'rev-parse', 'HEAD') == head and 'evil' not in (clone / 'p.hu').read_text()


def test_off_by_default_and_the_primary_cant_switch_it(signing, tmp_path, capsys):
    bare, other = _seed(tmp_path, signed=False)
    base, clone = _home(tmp_path, verify=False)
    assert main(base + ['plugin', 'bless', str(bare)]) == 0              # off: unsigned is fine
    assert (clone / 'p.hu').exists()
    ctx = Context(build_parser().parse_args(base + ['inspect']))
    assert ctx.config.primary_verify() == 'off'
    assert main(base + ['config', 'set', 'primary-verify', 'signed']) == 0
    _other_pushes(other, '{ picks: { this-machine: [ btop ] }  primary-verify: off }\n', signed=False)
    capsys.readouterr()
    main(base + ['plugin', 'sync'])                                      # held back, so it can't land
    assert 'commits without a good signature' in capsys.readouterr().out
    (clone / 'p.hu').write_text('{ primary-verify: off }\n')            # even if it got there
    ctx = Context(build_parser().parse_args(base + ['inspect']))
    assert ctx.config.primary_verify() == 'signed'
    capsys.readouterr()
    main(base + ['check'])
    assert 'is read only from your top config' in capsys.readouterr().out


def test_unsigned_commits_reads_gits_verdicts(signing, tmp_path):
    from configsys.runner import Runner
    bare, other = _seed(tmp_path, signed=True)
    _other_pushes(other, '{ }\n', signed=False)
    import shlex
    dq = shlex.quote(str(other))
    bad = plugins.unsigned_commits(Runner(pretend=False), dq, 'HEAD~1', 'HEAD')
    assert len(bad) == 1 and bad[0].endswith(' B')
    assert plugins.unsigned_commits(Runner(pretend=False), dq, None, 'HEAD~1') == []
