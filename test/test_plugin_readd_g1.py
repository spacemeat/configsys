'''review-2026-11-2 actions-22: re-running `plugin add <source>` without `--ref` keeps the pin it
already has — the decl's ref and the clone's checkout — instead of silently unpinning it.'''

import shutil
import subprocess

import pytest

from configsys import plugins

pytestmark = pytest.mark.real_runner  # real git clones in tmp dirs (conftest)


def _git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_a_bare_re_add_keeps_the_pin(tmp_path, capsys):
    from configsys.app import main
    src = tmp_path / 'src'
    src.mkdir()
    (src / 'plugin.hu').write_text('{ name: srcplug  requires-abi: 1  data: [ routes.hu ] }')
    (src / 'routes.hu').write_text('{ components: { stool: { install: [ { via: native } ] } } }')
    for cmd in (['init', '-q', '-b', 'main'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                ['add', '-A'], ['commit', '-qm', 'one'], ['tag', 'v1']):
        _git(src, *cmd)
    v1 = _git(src, 'rev-parse', 'HEAD')
    (src / 'routes.hu').write_text('{ components: { stool: { install: [ { via: native } ] }  t2: {} } }')
    _git(src, 'commit', '-qam', 'two')                    # main moves past v1
    home = ['--home', str(tmp_path / 'h'), '--os', 'pop']
    user = tmp_path / 'h' / '.config' / 'configsys' / 'configsys.hu'

    assert main(home + ['plugin', 'add', str(src), '--ref', 'v1', '--local']) == 0
    capsys.readouterr()
    assert main(home + ['plugin', 'add', str(src), '--local']) == 0
    out = capsys.readouterr().out
    assert 'already declared @v1' in out and 're-pinned' not in out
    assert [d.get('ref') for d in plugins.declared(user)] == ['v1']
    clone = tmp_path / 'h' / '.config' / 'configsys' / 'plugins' / 'src'
    assert _git(clone, 'rev-parse', 'HEAD') == v1         # the clone stayed at the pin


def test_upsert_decl_leaves_the_ref_when_none_is_given():
    decls = [{'source': 's', 'ref': 'v1'}]
    target, existed = plugins.upsert_decl(decls, 's', None)
    assert existed and target['ref'] == 'v1'
    plugins.upsert_decl(decls, 's', 'v2')
    assert decls == [{'source': 's', 'ref': 'v2'}]
