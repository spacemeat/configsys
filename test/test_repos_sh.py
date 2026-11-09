'''tools/repos.sh — the fleet push/tag helper asks before it touches any repo, never tags a dirty
worktree, and keeps a tag's `v` style (review-2026-11-2 tests-tools-19). Runs the real script against
a throwaway fleet of local repos with local bare origins (no network).'''

import shutil
import subprocess
from pathlib import Path

import pytest

from fakes import git

pytestmark = pytest.mark.skipif(shutil.which('git') is None or shutil.which('bash') is None,
                                reason='needs git and bash')

SCRIPT = Path(__file__).resolve().parent.parent / 'tools' / 'repos.sh'


def _repo(fleet, name, tag):
    bare = fleet / 'origins' / f'{name}.git'
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(bare)], check=True)
    repo = fleet / name
    subprocess.run(['git', 'clone', '-q', str(bare), str(repo)], check=True, capture_output=True)
    (repo / 'a.txt').write_text('1\n')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'one'); git(repo, 'tag', tag)
    (repo / 'a.txt').write_text('2\n')
    git(repo, 'commit', '-qam', 'two'); git(repo, 'push', '-q', 'origin', 'main', tag)
    return repo, bare


@pytest.fixture
def fleet(tmp_path):
    base, base_origin = _repo(tmp_path, 'configsys', '1.2.3')          # a tag without the v
    (base / 'tools').mkdir()
    shutil.copy(SCRIPT, base / 'tools' / 'repos.sh')
    (base / '.git' / 'info' / 'exclude').write_text('tools/\n')          # the copied script isn't "dirty"
    plug, plug_origin = _repo(tmp_path, 'configsys-plug', 'v0.1.0')
    (plug / 'a.txt').write_text('uncommitted\n')                         # a dirty worktree
    return base, base_origin, plug, plug_origin


def _run(base, *args, stdin=''):
    return subprocess.run(['bash', str(base / 'tools' / 'repos.sh'), *args], input=stdin,
                          capture_output=True, text=True, env={'PATH': '/usr/bin:/bin', 'NO_COLOR': '1',
                                                              'GIT_CONFIG_GLOBAL': '/dev/null',
                                                              'GIT_CONFIG_NOSYSTEM': '1'})


def _tags(repo):
    return set(git(repo, 'tag', '--list').split())


def test_tag_asks_first_and_no_means_nothing(fleet):
    base, base_origin, plug, _ = fleet
    r = _run(base, 'tag', stdin='n\n')
    assert r.returncode == 0, r.stderr
    assert 'nothing done' in r.stdout
    assert _tags(base) == {'1.2.3'} and _tags(plug) == {'v0.1.0'}
    assert _tags(base_origin) == {'1.2.3'}


def test_tag_yes_tags_clean_repos_in_their_style_and_skips_dirty_ones(fleet):
    base, base_origin, plug, plug_origin = fleet
    r = _run(base, 'tag', '--yes')
    assert r.returncode == 0, r.stderr
    assert _tags(base) == {'1.2.3', '1.2.4'}                            # no v added
    assert _tags(base_origin) == {'1.2.3', '1.2.4'}                     # pushed with the branch
    assert _tags(plug) == {'v0.1.0'} and _tags(plug_origin) == {'v0.1.0'}
    assert 'uncommitted' in r.stdout


def test_push_without_an_answer_pushes_nothing(fleet):
    base, base_origin, _plug, _ = fleet
    (base / 'b.txt').write_text('x\n')
    git(base, 'add', 'b.txt'); git(base, 'commit', '-qm', 'three')
    r = _run(base, 'push')                                               # stdin at EOF
    assert r.returncode == 0 and 'nothing done' in r.stdout
    assert git(base_origin, 'log', '-1', '--format=%s', 'main') == 'two'
