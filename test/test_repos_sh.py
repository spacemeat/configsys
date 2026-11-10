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


def _untagged(fleet, name):
    bare = fleet / 'origins' / f'{name}.git'
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(bare)], check=True)
    repo = fleet / name
    subprocess.run(['git', 'clone', '-q', str(bare), str(repo)], check=True, capture_output=True)
    (repo / 'a.txt').write_text('1\n')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'one')
    return repo, bare


def test_tag_prompt_names_only_the_repos_it_will_tag(fleet):
    '''The question counts and lists what will happen — not every repo in the fleet.'''
    base, _bo, _plug, _ = fleet
    r = _run(base, 'tag', stdin='n\n')
    assert 'tag 1 repo?' in r.stdout, r.stdout
    assert 'configsys  1.2.3 -> 1.2.4' in r.stdout
    assert 'configsys-plug  skip' in r.stdout                           # the dirty one, with why


def test_nothing_to_tag_asks_nothing(fleet):
    base, _bo, plug, _ = fleet
    git(plug, 'checkout', '-q', '--', 'a.txt')
    git(base, 'tag', '1.2.4'); git(plug, 'tag', 'v0.1.1')
    r = _run(base, 'tag')                                                # stdin at EOF: no prompt needed
    assert r.returncode == 0 and 'nothing to tag' in r.stdout and '[y/N]' not in r.stdout


def test_push_prompt_names_only_repos_ahead(fleet):
    base, _bo, _plug, _ = fleet
    (base / 'b.txt').write_text('x\n')
    git(base, 'add', 'b.txt'); git(base, 'commit', '-qm', 'three')
    r = _run(base, 'push', stdin='n\n')
    assert 'push 1 repo?' in r.stdout and 'configsys  main -> origin (1 commit)' in r.stdout


def test_tag_init_gives_an_untagged_plugin_its_first_tag(fleet, tmp_path):
    base, _bo, _plug, _ = fleet
    ver, ver_origin = _untagged(tmp_path, 'configsys-versions')
    r = _run(base, 'tag', stdin='n\n')
    assert 'configsys-versions  skip — no tags yet (`tools/repos.sh tag-init configsys-versions`' in r.stdout
    r = _run(base, 'tag-init', 'configsys-versions', '--yes')
    assert r.returncode == 0, r.stdout + r.stderr
    assert _tags(ver) == {'v0.1.0'} and _tags(ver_origin) == {'v0.1.0'}
    assert git(ver_origin, 'log', '-1', '--format=%s', 'main') == 'one'  # branch pushed with it
    again = _run(base, 'tag-init', 'configsys-versions', '--yes')
    assert again.returncode == 1 and 'already tagged' in again.stdout


def test_tag_init_refuses_the_base_repo_and_an_unknown_name(fleet):
    base, _bo, _plug, _ = fleet
    assert _run(base, 'tag-init', 'configsys', '--yes').returncode == 1
    assert _run(base, 'tag-init', 'configsys-nope', '--yes').returncode == 1


def test_the_primary_plugin_is_never_offered_a_tag(fleet, tmp_path):
    base, _bo, _plug, _ = fleet
    _untagged(tmp_path, 'configsys-user')
    cfg = tmp_path / 'top.hu'
    cfg.write_text('{\n    plugins: [\n        { source: "github:me/configsys-user"  ref: main  primary: true }\n    ]\n}\n')
    r = subprocess.run(['bash', str(base / 'tools' / 'repos.sh'), 'tag'], input='n\n', capture_output=True,
                       text=True, env={'PATH': '/usr/bin:/bin', 'NO_COLOR': '1', 'CONFIGSYS_CONFIG': str(cfg),
                                       'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'})
    assert 'configsys-user  skip — your primary plugin follows its branch' in r.stdout, r.stdout
    r = subprocess.run(['bash', str(base / 'tools' / 'repos.sh'), 'tag-init', 'configsys-user', '--yes'],
                       capture_output=True, text=True,
                       env={'PATH': '/usr/bin:/bin', 'NO_COLOR': '1', 'CONFIGSYS_CONFIG': str(cfg),
                            'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'})
    assert r.returncode == 1 and 'never version-tagged' in r.stdout
