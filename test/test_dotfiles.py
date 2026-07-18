import os
from pathlib import Path

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver
from configsys.drivers.dotfiles import DotFiles
from configsys.paths import Paths
from configsys.routes import Resolver
from configsys.runner import Runner


def df_unit(specs=None, comp='neovim'):
    fields = specs if specs is not None else {
        'config': {'src': 'neovim', 'dst': '$XDG_CONFIG_HOME/nvim'}}
    return ResolvedComponent(key=f'dotfiles\\{comp}', driver='dotfiles', comp=comp,
                             fields=fields)


def paths_for(tmp_path):
    return Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home'),
                      'CONFIGSYS_REPO': str(tmp_path / 'repo')})


# -- content root follows the layer that defined the component -------------

def test_src_anchors_at_the_defining_layers_dotfiles_dir(tmp_path):
    # a component defined in /somewhere/routes.hu sources from /somewhere/dotfiles/
    df = DotFiles(Runner(pretend=True), paths=paths_for(tmp_path))
    rc = ResolvedComponent(key='dotfiles\\x', driver='dotfiles', comp='x',
                           fields={'src': 'foo.sh', 'dst': '~/.foo.sh'},
                           source=str(tmp_path / 'myplugin' / 'routes.hu'))
    src, _tgt = df._pairs(rc)[0]
    assert src == tmp_path / 'myplugin' / 'dotfiles' / 'foo.sh'


def test_src_falls_back_to_repo_without_a_source(tmp_path):
    p = paths_for(tmp_path)
    df = DotFiles(Runner(pretend=True), paths=p)
    rc = ResolvedComponent(key='dotfiles\\x', driver='dotfiles', comp='x',
                           fields={'src': 'foo.sh', 'dst': '~/.foo.sh'})   # no source
    src, _tgt = df._pairs(rc)[0]
    assert src == p.dotfiles_dir / 'foo.sh'


def test_resolution_threads_the_defining_file_end_to_end(tmp_path):
    # a via:dotfiles component defined in its own routes file carries that file as rc.source,
    # so the driver anchors its content next to it — the configsys-user-as-a-plugin path
    routes = tmp_path / 'plug' / 'routes.hu'
    routes.parent.mkdir(parents=True)
    routes.write_text('{ os: { linux: {}  debian: { using: linux  native: apt } }'
                      '  components: { mycfg: { install: [ { via: dotfiles  src: m  dst: ~/m } ] } } }')
    rc = Resolver(str(routes), 'debian', '12').resolve_names(['mycfg'])['dotfiles\\mycfg']
    assert Path(rc.source) == routes                       # threaded from the defining file
    df = DotFiles(Runner(pretend=True), paths=paths_for(tmp_path))
    src, _tgt = df._pairs(rc)[0]
    assert src == routes.parent / 'dotfiles' / 'm'


def test_registry_has_dotfiles():
    assert isinstance(get_driver('dotfiles', Runner(pretend=True)), DotFiles)


def test_single_inline_spec():
    rc = ResolvedComponent(key='dotfiles\\arduino', driver='dotfiles', comp='arduino',
                           fields={'src': 'bash.d/arduino.sh', 'dst': '~/.bash.d/arduino.sh'})
    assert DotFiles._specs(rc) == [('arduino', 'bash.d/arduino.sh', '~/.bash.d/arduino.sh')]


def test_dst_env_expansion_defaults_xdg(tmp_path):
    p = paths_for(tmp_path)
    df = DotFiles(Runner(pretend=True), paths=p)
    src, tgt = df._pairs(df_unit())[0]
    assert src == p.dotfiles_dir / 'neovim'
    assert tgt == p.home / '.config' / 'nvim'   # $XDG_CONFIG_HOME default


def test_install_command_has_symlink_and_backup(tmp_path):
    r = Runner(pretend=True)
    DotFiles(r, paths=paths_for(tmp_path)).install(df_unit())
    cmd = r.calls[0]
    assert 'ln -sfn' in cmd
    assert '.pre-configsys' in cmd          # backs up an existing non-symlink
    assert 'nvim' in cmd
    assert 'sudo' not in cmd                # user-space


def test_no_specs_is_an_error(tmp_path):
    res = DotFiles(Runner(pretend=True), paths=paths_for(tmp_path)).install(df_unit(specs={}))
    assert not res.ok


def test_real_symlink_install_getversion_uninstall(tmp_path):
    p = paths_for(tmp_path)
    src_dir = p.dotfiles_dir / 'neovim'
    src_dir.mkdir(parents=True)
    (src_dir / 'init.lua').write_text('-- cfg')
    p.home.mkdir(parents=True)

    df = DotFiles(Runner(pretend=False), paths=p)
    rc = df_unit()
    assert df.get_version(rc) is None

    assert df.install(rc).ok
    target = p.home / '.config' / 'nvim'
    assert target.is_symlink()
    assert os.path.realpath(target) == os.path.realpath(src_dir)
    assert df.get_version(rc) == 'linked'

    df.uninstall(rc)
    assert not target.exists()


def test_existing_dir_is_backed_up_and_restored(tmp_path):
    p = paths_for(tmp_path)
    src_dir = p.dotfiles_dir / 'neovim'
    src_dir.mkdir(parents=True)
    (src_dir / 'init.lua').write_text('new')

    target = p.home / '.config' / 'nvim'
    target.mkdir(parents=True)
    (target / 'old.txt').write_text('old')

    df = DotFiles(Runner(pretend=False), paths=p)
    rc = df_unit()

    assert df.install(rc).ok
    assert target.is_symlink()
    backup = p.home / '.config' / 'nvim.pre-configsys'
    assert backup.is_dir() and (backup / 'old.txt').read_text() == 'old'

    df.uninstall(rc)
    assert target.is_dir() and not target.is_symlink()
    assert (target / 'old.txt').read_text() == 'old'   # original restored


def test_missing_source_fails(tmp_path):
    p = paths_for(tmp_path)
    p.home.mkdir(parents=True)
    # source dir not created -> install should fail, not silently link a dangling path
    res = DotFiles(Runner(pretend=False), paths=p).install(df_unit())
    assert not res.ok
    assert not (p.home / '.config' / 'nvim').exists()
