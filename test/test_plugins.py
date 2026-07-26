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
    files = plugins.layer_files(pdir, decls)              # -> [(path, role)]
    assert any(f.endswith('good/routes.hu') and role == 'plugin' for f, role in files)
    assert not any('future' in f for f, _ in files)       # ABI 99 unsupported -> skipped
    assert not any('missing' in f for f, _ in files)      # not synced -> skipped


def test_status_reports_synced_and_abi(tmp_path):
    pdir = tmp_path / 'plugins'
    _plugin(pdir, 'good', '{ name: good-plugin  requires-abi: 1 }', {})
    _plugin(pdir, 'future', '{ name: future-plugin  requires-abi: 99 }', {})
    rows = {r['name']: r for r in plugins.status(
        pdir, [{'source': 'x/good'}, {'source': 'x/future'}, {'source': 'x/nope'}])}
    assert rows['good-plugin']['synced'] and rows['good-plugin']['abi_ok']
    assert rows['future-plugin']['synced'] and not rows['future-plugin']['abi_ok']
    assert not rows['nope']['synced']                     # dir_name('x/nope') == 'nope'


# -- primary plugin + transitive declarations -----------------------------

def test_layer_files_marks_primary_role(tmp_path):
    pdir = tmp_path / 'plugins'
    _plugin(pdir, 'me', '{ name: me  requires-abi: 1  data: [ c.hu ] }', {'c.hu': '{ configs: [ x ] }'})
    plain = plugins.layer_files(pdir, [{'source': 'x/me'}])
    primary = plugins.layer_files(pdir, [{'source': 'x/me', 'primary': True}])
    assert plain and all(role == 'plugin' for _, role in plain)
    assert primary and all(role == 'primary' for _, role in primary)


def test_declared_reads_primary_flag(tmp_path):
    p = tmp_path / 'configsys.hu'
    p.write_text('{ plugins: [ { source: "github:me/cfg"  ref: v1  primary: true }'
                 '             { source: "github:x/other" } ] }')
    decls = plugins.declared(str(p))
    assert decls[0].get('primary') is True and 'primary' not in decls[1]
    assert plugins.primary_name(decls) == 'cfg'


def test_effective_declared_pulls_transitive_from_manifest(tmp_path):
    pdir = tmp_path / 'plugins'
    # the primary plugin's manifest declares a further plugin
    _plugin(pdir, 'cfg', '{ name: cfg  requires-abi: 1  plugins: [ { source: "github:x/blender"  ref: v1 } ] }', {})
    _plugin(pdir, 'blender', '{ name: blender  requires-abi: 1 }', {})
    top = tmp_path / 'configsys.hu'
    top.write_text('{ plugins: [ { source: "github:me/cfg"  primary: true } ] }')
    eff = plugins.effective_declared(str(top), pdir)
    srcs = [d['source'] for d in eff]
    assert srcs == ['github:me/cfg', 'github:x/blender']   # primary first, then its declared
    assert eff[0].get('primary') and 'primary' not in eff[1]   # transitive never inherits primary


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
    assert any(f.endswith('src/routes.hu') for f, _ in files)


def _git(cwd, *args):
    subprocess.run(['git', *args], cwd=cwd, check=True)


def _init_repo(src, branch='trunk'):
    src.mkdir()
    (src / 'plugin.hu').write_text('{ name: sp  requires-abi: 1  data: [ routes.hu ] }')
    (src / 'routes.hu').write_text('{ components: { sptool: { install: [ { via: native } ] } } }')
    (src / 'v.txt').write_text('A')
    _git(src, 'init', '-q'); _git(src, 'config', 'user.email', 't@t')
    _git(src, 'config', 'user.name', 't'); _git(src, 'add', '-A'); _git(src, 'commit', '-qm', 'A')
    _git(src, 'branch', '-M', branch)                      # deterministic branch name (any git)


@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_sync_follows_a_re_pointed_tag(tmp_path):
    # A pin to a MOVED tag must land on the tag's new commit — fetch --force refreshes it.
    src = tmp_path / 'src'
    _init_repo(src)
    _git(src, 'tag', 'v1')
    pdir = tmp_path / 'plugins'
    decl = [{'source': str(src), 'ref': 'v1'}]
    plugins.sync(Runner(pretend=False), pdir, decl)
    assert (pdir / 'src' / 'v.txt').read_text() == 'A'
    # move v1 onto a new commit
    (src / 'v.txt').write_text('B'); _git(src, 'add', '-A'); _git(src, 'commit', '-qm', 'B')
    _git(src, 'tag', '-f', 'v1')
    assert plugins.sync(Runner(pretend=False), pdir, decl) == [('src', 'updated')]
    assert (pdir / 'src' / 'v.txt').read_text() == 'B'    # was 'A' before the fetch --force fix


@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_sync_advances_a_branch_ref(tmp_path):
    # A branch ref must fast-forward on re-sync (checking out the local branch was a no-op).
    src = tmp_path / 'src'
    _init_repo(src, branch='trunk')
    pdir = tmp_path / 'plugins'
    decl = [{'source': str(src), 'ref': 'trunk'}]
    plugins.sync(Runner(pretend=False), pdir, decl)
    assert (pdir / 'src' / 'v.txt').read_text() == 'A'
    (src / 'v.txt').write_text('B'); _git(src, 'add', '-A'); _git(src, 'commit', '-qm', 'B')
    plugins.sync(Runner(pretend=False), pdir, decl)
    assert (pdir / 'src' / 'v.txt').read_text() == 'B'    # advanced to origin/trunk


@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_sync_reports_failed_on_a_bad_ref(tmp_path):
    # A checkout that can't resolve the ref is 'failed', not a silent 'cloned'/'updated'.
    src = tmp_path / 'src'
    _init_repo(src)
    _git(src, 'tag', 'v1')
    pdir = tmp_path / 'plugins'
    res = plugins.sync(Runner(pretend=False), pdir, [{'source': str(src), 'ref': 'nope'}])
    assert res == [('src', 'failed')]


def test_is_local_authored(tmp_path):
    p = tmp_path / 'plugins' / 'foo'
    assert plugins.is_local_authored(str(p), p)
    assert not plugins.is_local_authored('github:me/foo', p)
    assert not plugins.is_local_authored(str(tmp_path / 'elsewhere'), p)


def test_sync_is_local_noop_for_in_place_plugin(tmp_path):
    pdir = tmp_path / 'plugins'
    plug = pdir / 'myconfig'
    plug.mkdir(parents=True)
    (plug / 'plugin.hu').write_text('{ name: myconfig  requires-abi: 1 }')
    (plug / 'sentinel').write_text('local')                   # would vanish if cloned over
    res = plugins.sync(Runner(pretend=False), pdir, [{'source': str(plug), 'ref': None}])
    assert res == [('myconfig', 'local')]
    assert (plug / 'sentinel').read_text() == 'local'         # untouched


@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_plugin_init_create_then_merge(tmp_path, monkeypatch):
    from configsys.app import main
    from configsys.layers import materialize_string
    monkeypatch.setenv('CONFIGSYS_NO_DISCOVER', '1')
    cfgdir = tmp_path / 'home' / '.config' / 'configsys'
    cfgdir.mkdir(parents=True)
    (cfgdir / 'configsys.hu').write_text(
        '{ configs: [ dev ]  plugins: [ { source: "github:x/foo"  ref: v1 } ]'
        '  profiles: { mine: [ btop ] } }')
    st = cfgdir / 'dotfiles' / 'htop'
    st.mkdir(parents=True)
    (st / 'htoprc').write_text('cfg')
    base = ['--home', str(tmp_path / 'home'), '--os', 'pop', 'plugin', 'init']

    assert main(base + ['myc']) == 0
    plug = cfgdir / 'plugins' / 'myc'
    m = materialize_string((plug / 'plugin.hu').read_text())
    assert m['name'] == 'myc' and m['data'] == ['myc.hu']
    assert m['plugins'][0]['source'] == 'github:x/foo'          # carried as transitive
    assert 'mine' in materialize_string((plug / 'myc.hu').read_text())['profiles']
    assert (plug / 'dotfiles' / 'htop' / 'htoprc').read_text() == 'cfg'   # dotfiles moved in
    assert not (cfgdir / 'dotfiles' / 'htop').exists()          # local store emptied
    decls = plugins.declared(str(cfgdir / 'configsys.hu'))
    assert decls == [{'source': str(plug), 'ref': None, 'primary': True}]
    cfg = materialize_string((cfgdir / 'configsys.hu').read_text())
    assert 'profiles' not in cfg and 'configs' in cfg          # profiles moved out; configs stays

    # a primary now exists -> a second init MERGES leftover local-store dotfiles into it
    gdb = cfgdir / 'dotfiles' / 'gdb'
    gdb.mkdir(parents=True)
    (gdb / 'gdbinit').write_text('x')
    assert main(base) == 0
    assert (plug / 'dotfiles' / 'gdb' / 'gdbinit').read_text() == 'x'


def test_remove_sections_preserves_the_rest(tmp_path):
    p = tmp_path / 'configsys.hu'
    p.write_text('{\n    // keep\n    configs: [ dev ]\n    profiles: { mine: [ btop ] }\n'
                 '    pins: { steam: flatpak }\n}\n')
    assert plugins.remove_sections(str(p), ['profiles']) == ['profiles']
    text = p.read_text()
    assert '// keep' in text and 'configs:' in text and 'pins:' in text
    assert 'profiles:' not in text


def test_plugin_set_source_swaps_and_keeps_primary(tmp_path, monkeypatch):
    from configsys.app import main
    monkeypatch.setenv('CONFIGSYS_NO_DISCOVER', '1')
    cfgdir = tmp_path / 'home' / '.config' / 'configsys'
    cfgdir.mkdir(parents=True)
    (cfgdir / 'configsys.hu').write_text(
        '{ plugins: [ { source: /local/myc  primary: true } ] }')
    home = ['--home', str(tmp_path / 'home'), '--os', 'pop']
    assert main(home + ['plugin', 'set-source', 'myc', 'github:me/myc']) == 0
    decls = plugins.declared(str(cfgdir / 'configsys.hu'))
    assert decls == [{'source': 'github:me/myc', 'ref': None, 'primary': True}]


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


@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_cli_plugin_add_lands_in_primary_when_set(tmp_path, capsys):
    from configsys.app import main

    def _repo(name, plugin_hu, extra):
        d = tmp_path / name
        d.mkdir()
        (d / 'plugin.hu').write_text(plugin_hu)
        for fn, txt in extra.items():
            (d / fn).write_text(txt)
        for cmd in (['init', '-q'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                    ['add', '-A'], ['commit', '-qm', 'i'], ['tag', 'v1']):
            subprocess.run(['git', *cmd], cwd=d, check=True)
        return d

    prim = _repo('prim', '{ name: prim  requires-abi: 1  data: [ d.hu ]  plugins: [] }',
                 {'d.hu': '{ profiles: { p: [ btop ] } }'})
    addon = _repo('addon', '{ name: addon  requires-abi: 1  data: [ r.hu ] }',
                  {'r.hu': '{ components: { ac: { install: [ { via: native } ] } } }'})
    home = ['--home', str(tmp_path), '--os', 'pop']
    top = tmp_path / '.config' / 'configsys' / 'configsys.hu'
    prim_manifest = tmp_path / '.config' / 'configsys' / 'plugins' / 'prim' / 'plugin.hu'

    assert main(home + ['plugin', 'bless', str(prim)]) == 0     # prim becomes the primary
    capsys.readouterr()

    # with a primary set, `add` lands in the PRIMARY's transitive plugins:, not the top config
    assert main(home + ['plugin', 'add', str(addon)]) == 0
    assert 'in the primary plugin (prim)' in capsys.readouterr().out
    assert 'addon' in prim_manifest.read_text()                 # rode the primary (portable)
    assert 'addon' not in top.read_text()                       # NOT in the per-machine top config
    # ...and it's transitively effective + synced locally right away
    assert main(home + ['plugin', 'list']) == 0
    assert 'addon' in capsys.readouterr().out

    # --local forces the per-machine top config even with a primary set
    assert main(home + ['plugin', 'add', str(addon), '--local']) == 0
    assert 'this machine only' in capsys.readouterr().out
    assert 'addon' in top.read_text()


@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_cli_plugin_remove_and_update_are_primary_aware(tmp_path, capsys):
    from configsys.app import main

    def _repo(name, plugin_hu, extra):
        d = tmp_path / name
        d.mkdir()
        (d / 'plugin.hu').write_text(plugin_hu)
        for fn, txt in extra.items():
            (d / fn).write_text(txt)
        for cmd in (['init', '-q'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                    ['add', '-A'], ['commit', '-qm', 'i'], ['tag', 'v1']):
            subprocess.run(['git', *cmd], cwd=d, check=True)
        return d

    prim = _repo('prim', '{ name: prim  requires-abi: 1  data: [ d.hu ]  plugins: [] }',
                 {'d.hu': '{ profiles: { p: [ btop ] } }'})
    addon = _repo('addon', '{ name: addon  requires-abi: 1  data: [ r.hu ] }',
                  {'r.hu': '{ components: { ac: { install: [ { via: native } ] } } }'})
    home = ['--home', str(tmp_path), '--os', 'pop']
    top = tmp_path / '.config' / 'configsys' / 'configsys.hu'
    prim_manifest = tmp_path / '.config' / 'configsys' / 'plugins' / 'prim' / 'plugin.hu'
    synced_addon = tmp_path / '.config' / 'configsys' / 'plugins' / 'addon'

    main(home + ['plugin', 'bless', str(prim)]); capsys.readouterr()
    main(home + ['plugin', 'add', str(addon)]); capsys.readouterr()      # lands in the primary
    assert 'addon' in prim_manifest.read_text() and synced_addon.exists()

    # update --ref: re-pins in the PRIMARY's manifest (where addon is declared), not the top config
    assert main(home + ['plugin', 'update', 'addon', '--ref', 'v1']) == 0
    out = capsys.readouterr().out
    assert 're-pinned' in out and 'in prim' in out
    assert 'ref: v1' in prim_manifest.read_text()
    assert 'addon' not in top.read_text()

    # remove: undeclares from the PRIMARY's manifest AND deletes the synced clone
    assert main(home + ['plugin', 'remove', 'addon']) == 0
    out = capsys.readouterr().out
    assert 'removed' in out and 'from prim' in out
    assert 'addon' not in prim_manifest.read_text()
    assert not synced_addon.exists()


def test_cli_plugin_add_uses_top_config_without_a_primary(tmp_path, capsys):
    from configsys.app import main
    src = tmp_path / 'np'
    src.mkdir()
    (src / 'plugin.hu').write_text('{ name: np  requires-abi: 1  data: [ r.hu ] }')
    (src / 'r.hu').write_text('{ components: { npc: { install: [ { via: native } ] } } }')
    for cmd in (['init', '-q'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                ['add', '-A'], ['commit', '-qm', 'i']):
        subprocess.run(['git', *cmd], cwd=src, check=True)
    home = ['--home', str(tmp_path), '--os', 'pop']
    assert main(home + ['plugin', 'add', str(src)]) == 0
    out = capsys.readouterr().out
    assert 'this machine only' not in out                       # no primary -> plain top-config add
    assert 'np' in (tmp_path / '.config' / 'configsys' / 'configsys.hu').read_text()


def test_set_declared_round_trips_primary(tmp_path):
    p = tmp_path / 'configsys.hu'
    p.write_text('{\n    plugins: [ { source: "github:a/b" } ]\n}\n')
    plugins.set_declared(str(p), [{'source': 'github:a/b', 'ref': 'v1', 'primary': True}])
    assert 'primary: true' in p.read_text()
    assert plugins.declared(str(p))[0].get('primary') is True


@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_cli_plugin_bless_and_unbless(tmp_path, capsys):
    from configsys.app import main
    src = tmp_path / 'src'
    src.mkdir()
    (src / 'plugin.hu').write_text('{ name: mine  requires-abi: 1  data: [ d.hu ] }')
    (src / 'd.hu').write_text('{ configs: [ solo ]  profiles: { solo: [ btop ] } }')
    for cmd in (['init', '-q'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                ['add', '-A'], ['commit', '-qm', 'i'], ['tag', 'v1']):
        subprocess.run(['git', *cmd], cwd=src, check=True)
    home = ['--home', str(tmp_path), '--os', 'pop']

    # bless finds + syncs + marks primary; its machine settings (configs: [solo]) then apply
    assert main(home + ['plugin', 'bless', str(src)]) == 0
    assert 'blessed' in capsys.readouterr().out
    cfg = (tmp_path / '.config' / 'configsys' / 'configsys.hu').read_text()
    assert 'primary: true' in cfg
    assert main(home + ['inspect']) == 0
    assert 'solo' in capsys.readouterr().out                 # primary's configs activated

    # unbless clears it -> the primary's configs no longer apply
    assert main(home + ['plugin', 'unbless']) == 0
    assert 'cleared' in capsys.readouterr().out
    assert 'primary: true' not in (tmp_path / '.config' / 'configsys' / 'configsys.hu').read_text()


def test_cli_plugin_bless_unknown_source_changes_nothing(tmp_path, capsys):
    from configsys.app import main
    home = ['--home', str(tmp_path), '--os', 'pop']
    rc = main(home + ['plugin', 'bless', 'github:nobody/does-not-exist-xyz'])
    assert rc == 1
    assert 'could not find' in capsys.readouterr().out
    cfg = tmp_path / '.config' / 'configsys' / 'configsys.hu'
    assert not cfg.exists() or 'primary: true' not in cfg.read_text()   # no broken primary left
