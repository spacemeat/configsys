'''review-2026-11-2 A3: removing or replacing a plugin never destroys work that exists nowhere else —
unpushed commits, uncommitted edits, stashes, a repo with no remote, a primary authored in place by
`plugin init`. `plugin remove` refuses and names it (--force deletes anyway); `plugin add --replace`
keeps such a copy as `<name>.replaced-<stamp>` and keeps the primary designation.'''

import shutil
import subprocess

import pytest

from configsys import plugins, primarygit
from configsys.app import main

pytestmark = [pytest.mark.skipif(shutil.which('git') is None, reason='git not available'),
              pytest.mark.real_runner]


def _git(cwd, *a):
    return subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _remote(tmp_path, name):
    bare = tmp_path / 'remotes' / name
    bare.parent.mkdir(exist_ok=True)
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(bare)], check=True)
    seed = tmp_path / f'seed-{name}'
    subprocess.run(['git', 'clone', '-q', str(bare), str(seed)], check=True, capture_output=True)
    (seed / 'plugin.hu').write_text(f'{{ name: {name}  requires-abi: 1  data: [ p.hu ] }}\n')
    (seed / 'p.hu').write_text('{ picks: { this-machine: [ btop ] } }\n')
    _git(seed, 'add', '-A'); _git(seed, 'commit', '-qm', 'A'); _git(seed, 'push', '-q', 'origin', 'main')
    return bare


@pytest.fixture
def home(tmp_path):
    h = tmp_path / 'home'
    return h, ['--home', str(h), '--os', 'pop', '-q']


def _clone(h, name):
    return h / '.config' / 'configsys' / 'plugins' / name


def test_local_work_names_each_kind_of_unsaved_work(tmp_path):
    bare = _remote(tmp_path, 'w')
    c = tmp_path / 'c'
    subprocess.run(['git', 'clone', '-q', str(bare), str(c)], check=True, capture_output=True)
    assert primarygit.local_work(c) == []
    (c / 'p.hu').write_text('{ picks: { this-machine: [ zsh ] } }\n')
    assert any('uncommitted' in s for s in primarygit.local_work(c))
    _git(c, 'commit', '-qam', 'B')
    assert any('not on any remote' in s for s in primarygit.local_work(c))
    lone = tmp_path / 'lone'
    lone.mkdir(); _git(lone, 'init', '-q'); (lone / 'x').write_text('x'); _git(lone, 'add', '-A')
    _git(lone, 'commit', '-qm', 'x')
    assert any('no remote' in s for s in primarygit.local_work(lone))
    assert any('its own source' in s for s in primarygit.local_work(lone, str(lone)))


def test_local_work_ignores_untracked_bytecode(tmp_path):
    # Python writes __pycache__/*.pyc next to a trusted code plugin's module: not anyone's work
    bare = _remote(tmp_path, 'w')
    c = tmp_path / 'c'
    subprocess.run(['git', 'clone', '-q', str(bare), str(c)], check=True, capture_output=True)
    (c / '__pycache__').mkdir()
    (c / '__pycache__' / 'driver.cpython-310.pyc').write_bytes(b'\0')
    (c / 'stray.pyc').write_bytes(b'\0')
    assert primarygit.local_work(c) == []
    (c / 'notes.txt').write_text('mine\n')                          # a real untracked file still counts
    assert any('uncommitted' in s and 'notes.txt' in s for s in primarygit.local_work(c))


def test_remove_refuses_a_primary_with_unpushed_commits(tmp_path, home, capsys):
    h, base = home
    bare = _remote(tmp_path, 'prim')
    assert main(base + ['plugin', 'bless', str(bare)]) == 0
    assert main(base + ['picks', 'add', 'jq']) == 0                     # a journal commit, not pushed
    capsys.readouterr()
    assert main(base + ['plugin', 'remove', 'prim']) == 1
    out = capsys.readouterr().out
    assert 'not pushed' in out and '--force' in out
    assert _clone(h, 'prim').exists() and 'jq' in (_clone(h, 'prim') / 'p.hu').read_text()
    assert plugins.primary_name(plugins.declared(h / '.config' / 'configsys' / 'configsys.hu')) == 'prim'
    assert main(base + ['plugin', 'remove', 'prim', '--force']) == 0       # you asked for it
    assert not _clone(h, 'prim').exists()


def test_remove_refuses_a_dirty_third_party_clone_and_allows_a_clean_one(tmp_path, home, capsys):
    h, base = home
    bare = _remote(tmp_path, 'third')
    assert main(base + ['plugin', 'add', str(bare), '--local']) == 0
    (_clone(h, 'third') / 'p.hu').write_text('{ picks: { this-machine: [ zsh ] } }\n')
    capsys.readouterr()
    assert main(base + ['plugin', 'remove', 'third']) == 1
    assert 'uncommitted' in capsys.readouterr().out and _clone(h, 'third').exists()
    _git(_clone(h, 'third'), 'checkout', '-q', '--', 'p.hu')
    assert main(base + ['plugin', 'remove', 'third']) == 0
    assert not _clone(h, 'third').exists()


def test_the_tui_x_key_is_refused_the_same_way(tmp_path, home):
    from configsys import actions
    from configsys.app import Context, build_parser
    h, base = home
    bare = _remote(tmp_path, 'prim')
    assert main(base + ['plugin', 'bless', str(bare)]) == 0
    assert main(base + ['picks', 'add', 'jq']) == 0
    ctx = Context(build_parser().parse_args(base + ['inspect']))
    ok, msg = actions.plugin_remove(ctx, 'prim')                         # what Plugins `x` calls
    assert not ok and 'not pushed' in msg and _clone(h, 'prim').exists()


def test_replace_keeps_unpushed_work_aside_and_stays_primary(tmp_path, home, capsys):
    h, base = home
    bare = _remote(tmp_path, 'prim')
    assert main(base + ['plugin', 'bless', str(bare)]) == 0
    assert main(base + ['picks', 'add', 'jq']) == 0
    alt = tmp_path / 'alt'
    alt.mkdir()
    alt_bare = _remote(alt, 'prim')
    capsys.readouterr()
    assert main(base + ['plugin', 'add', str(alt_bare), '--replace']) == 0
    out = capsys.readouterr().out
    assert 'kept the old copy' in out
    kept = [p for p in _clone(h, 'prim').parent.iterdir() if p.name.startswith('prim.replaced-')]
    assert len(kept) == 1 and 'picks add jq' in _git(kept[0], 'log', '--format=%s')
    decls = plugins.declared(h / '.config' / 'configsys' / 'configsys.hu')
    assert plugins.primary_name(decls) == 'prim'                        # still your primary
    assert [d['source'] for d in decls if d.get('primary')] == [str(alt_bare)]
