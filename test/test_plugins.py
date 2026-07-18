'''Data plugins (P1): declare in `plugins:`, sync from git, contribute os/component layers.
The code/trust/ABI-gate escalation is P2 (see docs/plugins.md).'''

import os
import shutil
import subprocess

import pytest

from configsys import plugins
from configsys.routes import Resolver
from configsys.runner import Runner

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')


def _plugin(plugins_dir, name, manifest, files):
    d = plugins_dir / name
    d.mkdir(parents=True)
    (d / 'plugin.hu').write_text(manifest)
    for fname, text in files.items():
        (d / fname).write_text(text)
    return d


# -- source / manifest parsing --------------------------------------------

def test_source_url_and_dir_name():
    assert plugins.source_url('github:a/b') == 'https://github.com/a/b.git'
    assert plugins.source_url('gitlab:a/b') == 'https://gitlab.com/a/b.git'
    assert plugins.source_url('/local/path') == '/local/path'
    assert plugins.dir_name('github:someone/configsys-opensuse') == 'configsys-opensuse'
    assert plugins.dir_name('/x/y/myplugin.git') == 'myplugin'


def test_declared_reads_plugins_list(tmp_path):
    p = tmp_path / 'configsys.hu'
    # a github/gitlab source has a colon, so it must be quoted (humon); a bare path needn't be
    p.write_text('{ plugins: [ { source: "github:a/b"  ref: v1 }  { source: /x/y } ] }')
    assert plugins.declared(str(p)) == [
        {'source': 'github:a/b', 'ref': 'v1'}, {'source': '/x/y', 'ref': None}]


def test_declared_empty_when_absent(tmp_path):
    p = tmp_path / 'configsys.hu'
    p.write_text('{ configs: [ dev ] }')
    assert plugins.declared(str(p)) == []


# -- layer selection (uses what's on disk) --------------------------------

def test_layer_files_skips_unsynced_and_abi_incompatible(tmp_path):
    pdir = tmp_path / 'plugins'
    _plugin(pdir, 'good', '{ name: good  requires-abi: 1  data: [ routes.hu ] }',
            {'routes.hu': '{ components: { g: { install: [ { via: native } ] } } }'})
    _plugin(pdir, 'future', '{ name: future  requires-abi: 99 }',
            {'routes.hu': '{ components: { f: { install: [ { via: native } ] } } }'})
    decls = [{'source': 'x/good'}, {'source': 'x/future'}, {'source': 'x/missing'}]
    files = plugins.layer_files(pdir, decls)
    assert any(f.endswith('good/routes.hu') for f in files)
    assert not any('future' in f for f in files)          # ABI 99 unsupported -> skipped
    assert not any('missing' in f for f in files)         # not synced -> skipped


def test_status_reports_synced_and_abi(tmp_path):
    pdir = tmp_path / 'plugins'
    _plugin(pdir, 'good', '{ name: good-plugin  requires-abi: 1 }', {})
    _plugin(pdir, 'future', '{ name: future-plugin  requires-abi: 99 }', {})
    rows = {r['name']: r for r in plugins.status(
        pdir, [{'source': 'x/good'}, {'source': 'x/future'}, {'source': 'x/nope'}])}
    assert rows['good-plugin']['synced'] and rows['good-plugin']['abi_ok']
    assert rows['future-plugin']['synced'] and not rows['future-plugin']['abi_ok']
    assert not rows['nope']['synced']                     # dir_name('x/nope') == 'nope'


# -- resolution: plugin adds a component AND an os block (derivative distro) --

def test_plugin_component_and_os_block_resolve(tmp_path):
    pdir = tmp_path / 'plugins'
    _plugin(pdir, 'p', '{ name: p  requires-abi: 1  data: [ routes.hu ] }',
            {'routes.hu': '{ os: { linuxmint: { using: ubuntu } } '
                          '  components: { ptool: { install: [ { via: native } ] } } }'})
    files = plugins.layer_files(pdir, [{'source': 'x/p'}])
    # ptool resolves, and on the plugin's own os block (mint -> ubuntu -> apt)
    r = Resolver(ROUTES, 'linuxmint', '21', 'x86_64', plugin_files=files)
    units = r.resolve_names(['ptool'])
    assert 'apt\\ptool' in units
    assert r.components['ptool'].source.endswith('p/routes.hu')


# -- sync (real git, local repo, no network) ------------------------------

@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_sync_clones_a_local_git_repo(tmp_path):
    src = tmp_path / 'src'
    src.mkdir()
    (src / 'plugin.hu').write_text('{ name: lp  requires-abi: 1  data: [ routes.hu ] }')
    (src / 'routes.hu').write_text('{ components: { lptool: { install: [ { via: native } ] } } }')
    for cmd in (['init', '-q'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                ['add', '-A'], ['commit', '-qm', 'init'], ['tag', 'v1']):
        subprocess.run(['git', *cmd], cwd=src, check=True)

    pdir = tmp_path / 'plugins'
    plugins.sync(Runner(pretend=False), pdir, [{'source': str(src), 'ref': 'v1'}])
    assert (pdir / 'src' / 'routes.hu').exists()          # cloned at the pinned tag
    files = plugins.layer_files(pdir, [{'source': str(src), 'ref': 'v1'}])
    assert any(f.endswith('src/routes.hu') for f in files)


# -- editing the plugins: list (comment-preserving) -----------------------

def test_set_declared_inserts_and_preserves_comments(tmp_path):
    p = tmp_path / 'configsys.hu'
    p.write_text('{\n    // keep me\n    configs: [ dev ]\n}\n')
    plugins.set_declared(str(p), [{'source': 'github:a/b', 'ref': 'v1'}])
    text = p.read_text()
    assert '// keep me' in text                              # untouched
    assert plugins.declared(str(p)) == [{'source': 'github:a/b', 'ref': 'v1'}]


def test_set_declared_replaces_existing_and_keeps_the_rest(tmp_path):
    p = tmp_path / 'configsys.hu'
    p.write_text('{\n    // c\n    scope: user\n'
                 '    plugins: [ { source: "github:a/b"  ref: v1 } ]\n}\n')
    plugins.set_declared(str(p), [{'source': 'github:a/b', 'ref': 'v2'},
                                  {'source': '/x/y', 'ref': None}])
    text = p.read_text()
    assert '// c' in text and 'scope: user' in text
    assert plugins.declared(str(p)) == [{'source': 'github:a/b', 'ref': 'v2'},
                                        {'source': '/x/y', 'ref': None}]


def test_set_declared_empty(tmp_path):
    p = tmp_path / 'configsys.hu'
    p.write_text('{\n    plugins: [ { source: /x } ]\n}\n')
    plugins.set_declared(str(p), [])
    assert plugins.declared(str(p)) == []


@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_cli_plugin_add_and_remove(tmp_path, capsys):
    from configsys.app import main
    src = tmp_path / 'src'
    src.mkdir()
    (src / 'plugin.hu').write_text('{ name: cli-plug  requires-abi: 1  data: [ routes.hu ] }')
    (src / 'routes.hu').write_text('{ components: { clico: { install: [ { via: native } ] } } }')
    for cmd in (['init', '-q'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                ['add', '-A'], ['commit', '-qm', 'i'], ['tag', 'v1']):
        subprocess.run(['git', *cmd], cwd=src, check=True)
    home = ['--home', str(tmp_path), '--os', 'pop']

    assert main(home + ['plugin', 'add', str(src), '--ref', 'v1']) == 0
    out = capsys.readouterr().out
    assert 'added' in out and 'cloned' in out
    # declared + synced + resolvable
    assert main(home + ['plugin', 'list']) == 0
    assert 'cli-plug' in capsys.readouterr().out
    synced = tmp_path / '.config' / 'configsys' / 'plugins' / 'src'
    assert synced.exists()

    assert main(home + ['plugin', 'remove', 'cli-plug']) == 0
    assert 'removed' in capsys.readouterr().out
    assert not synced.exists()                               # dir deleted
