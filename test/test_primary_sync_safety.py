'''Primary-push plan, phase 0 (docs/todo/primary-push-plan.md): sync never discards local edits, says
when a branch diverged or has unpushed commits, keeps a primary attached to its branch even with no
`ref:`, and `update --latest` never re-pins a branch-following primary to a version tag.'''

import shutil
import subprocess
import types

import pytest

from configsys import actions, plugins
from configsys.runner import Runner

pytestmark = pytest.mark.skipif(shutil.which('git') is None, reason='git not available')


def _git(cwd, *a):
    return subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _ident(cwd):
    _git(cwd, 'config', 'user.email', 't@t')
    _git(cwd, 'config', 'user.name', 't')


@pytest.fixture
def remote(tmp_path):
    '''A bare remote `prim` (branch main, tag v1) plus `other`: a clone standing in for another machine.'''
    bare = tmp_path / 'prim'
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(bare)], check=True)
    other = tmp_path / 'other'
    subprocess.run(['git', 'clone', '-q', str(bare), str(other)], check=True, capture_output=True)
    _ident(other)
    (other / 'plugin.hu').write_text('{ name: prim  requires-abi: 1  data: [ p.hu ] }\n')
    (other / 'p.hu').write_text('{ picks: { laptop: [ btop ] } }\n')
    _git(other, 'add', '-A'); _git(other, 'commit', '-qm', 'A'); _git(other, 'tag', 'v1')
    _git(other, 'push', '-q', 'origin', 'main', '--tags')
    return bare, other


def _push_change(other, text, tag=None):
    (other / 'p.hu').write_text(text)
    _git(other, 'commit', '-qam', text[:20])
    if tag:
        _git(other, 'tag', tag)
    _git(other, 'push', '-q', 'origin', 'main', '--tags')


def _sync(pdir, decl):
    return plugins.sync(Runner(pretend=False), pdir, [decl])


def test_a_tag_pinned_plugin_keeps_uncommitted_edits(tmp_path, remote):
    bare, other = remote
    pdir = tmp_path / 'plugins'
    decl = {'source': str(bare), 'ref': 'v1', 'primary': True}
    assert _sync(pdir, decl) == [('prim', 'cloned')]
    mine = pdir / 'prim' / 'p.hu'
    mine.write_text('{ picks: { laptop: [ btop  fzf ] } }\n')           # an uncommitted edit
    _push_change(other, '{ picks: { laptop: [ htop ] } }\n', tag='v2')
    decl['ref'] = 'v2'
    assert _sync(pdir, decl) == [('prim', 'kept')]                      # used to be --force: edit lost
    assert 'fzf' in mine.read_text()
    assert 'local changes' in plugins.sync_note('prim', 'kept', pdir)


def test_a_no_ref_primary_follows_its_default_branch_attached(tmp_path, remote):
    bare, other = remote
    pdir = tmp_path / 'plugins'
    decl = {'source': str(bare), 'primary': True}
    _sync(pdir, decl)
    clone = pdir / 'prim'
    assert _git(clone, 'symbolic-ref', '--short', 'HEAD') == 'main'     # attached, not detached
    _push_change(other, '{ picks: { laptop: [ htop ] } }\n')
    assert _sync(pdir, decl) == [('prim', 'updated')]
    assert 'htop' in (clone / 'p.hu').read_text()                        # fast-forwarded
    (clone / 'p.hu').write_text('{ picks: { laptop: [ mine ] } }\n')     # dirty, then remote moves
    _push_change(other, '{ picks: { laptop: [ newer ] } }\n')
    assert _sync(pdir, decl) == [('prim', 'kept')]
    assert 'mine' in (clone / 'p.hu').read_text()


def test_a_non_primary_without_ref_still_detaches_but_never_forces(tmp_path, remote):
    bare, other = remote
    pdir = tmp_path / 'plugins'
    decl = {'source': str(bare)}
    _sync(pdir, decl)
    clone = pdir / 'prim'
    (clone / 'p.hu').write_text('edited\n')
    _push_change(other, '{ picks: { laptop: [ htop ] } }\n')
    assert _sync(pdir, decl) == [('prim', 'kept')]
    assert (clone / 'p.hu').read_text() == 'edited\n'


def test_branch_ahead_and_diverged_are_reported(tmp_path, remote):
    bare, other = remote
    pdir = tmp_path / 'plugins'
    decl = {'source': str(bare), 'ref': 'main', 'primary': True}
    _sync(pdir, decl)
    clone = pdir / 'prim'
    _ident(clone)
    (clone / 'plugin.hu').write_text('{ name: prim  requires-abi: 1  data: [ p.hu ]  x: 1 }\n')
    _git(clone, 'commit', '-qam', 'local')
    assert _sync(pdir, decl) == [('prim', 'ahead')]
    assert plugins.branch_state(Runner(pretend=False), clone, 'main') == ('main', 1, 0, False)
    _push_change(other, '{ picks: { laptop: [ htop ] } }\n')              # another machine pushed
    assert _sync(pdir, decl) == [('prim', 'diverged')]
    assert 'another machine' in plugins.sync_note('prim', 'diverged', pdir)
    assert _git(clone, 'rev-list', '--count', 'HEAD') == '2'             # local commit untouched


def _update_ctx(tmp_path, decl):
    user = tmp_path / 'user.hu'
    user.write_text('{ }\n')
    plugins.set_declared(user, [decl])
    ctx = types.SimpleNamespace(
        runner=Runner(pretend=False),
        paths=types.SimpleNamespace(user_config_file=user, plugins_dir=tmp_path / 'plugins',
                                    plugin_trust_file=tmp_path / 't.hu', plugin_lock_file=tmp_path / 'l.hu',
                                    glue_locations_file=tmp_path / 'g.tsv'))
    ctx.invalidate = ctx.ensure_plugin_code = lambda: None
    return ctx, user


def test_update_latest_keeps_a_branch_following_primary_on_its_branch(tmp_path, remote):
    bare, other = remote                                                 # the repo has tag v1
    decl = {'source': str(bare), 'ref': 'main', 'primary': True}
    ctx, user = _update_ctx(tmp_path, decl)
    _sync(ctx.paths.plugins_dir, decl)
    ok, msg, _r = actions.plugin_update(ctx, 'prim', latest=True)
    assert ok and 'follows its branch' in msg
    assert plugins.declared(user)[0]['ref'] == 'main'                   # not re-pinned to v1


def test_update_latest_moves_a_tag_pinned_primary_to_the_newest_tag(tmp_path, remote):
    bare, other = remote
    decl = {'source': str(bare), 'ref': 'v1', 'primary': True}
    ctx, user = _update_ctx(tmp_path, decl)
    _sync(ctx.paths.plugins_dir, decl)
    _push_change(other, '{ picks: { laptop: [ htop ] } }\n', tag='v2')
    _git(ctx.paths.plugins_dir / 'prim', 'fetch', '-q', '--tags')
    ok, _msg, _r = actions.plugin_update(ctx, 'prim', latest=True)
    assert ok and plugins.declared(user)[0]['ref'] == 'v2'


def test_bless_records_the_branch(tmp_path, remote, capsys):
    from configsys.app import main
    bare, _other = remote
    home = tmp_path / 'home'
    assert main(['--home', str(home), '--os', 'pop', '-q', 'plugin', 'bless', str(bare)]) == 0
    decls = plugins.declared(home / '.config' / 'configsys' / 'configsys.hu')
    assert decls == [{'source': str(bare), 'ref': 'main', 'primary': True}]


def test_commits_on_a_detached_head_are_not_stranded(tmp_path, remote):
    bare, other = remote
    pdir = tmp_path / 'plugins'
    _sync(pdir, {'source': str(bare)})                                  # detached at origin/HEAD
    clone = pdir / 'prim'
    _ident(clone)
    (clone / 'plugin.hu').write_text('{ name: prim  requires-abi: 1  data: [ p.hu ]  x: 1 }\n')
    _git(clone, 'commit', '-qam', 'on a detached head')
    head = _git(clone, 'rev-parse', 'HEAD')
    assert _sync(pdir, {'source': str(bare), 'ref': 'main', 'primary': True}) == [('prim', 'kept')]
    assert _git(clone, 'rev-parse', 'HEAD') == head


def test_cli_sync_explains_divergence(tmp_path, remote, capsys):
    from configsys.app import main
    bare, other = remote
    home = tmp_path / 'home'
    base = ['--home', str(home), '--os', 'pop', '-q']
    assert main(base + ['plugin', 'bless', str(bare)]) == 0
    clone = home / '.config' / 'configsys' / 'plugins' / 'prim'
    _ident(clone)
    (clone / 'plugin.hu').write_text('{ name: prim  requires-abi: 1  data: [ p.hu ]  x: 1 }\n')
    _git(clone, 'commit', '-qam', 'local')
    _push_change(other, '{ picks: { laptop: [ htop ] } }\n')
    capsys.readouterr()
    assert main(base + ['plugin', 'sync']) == 0
    out = capsys.readouterr().out
    assert 'diverged prim' in out and 'another machine pushed' in out
