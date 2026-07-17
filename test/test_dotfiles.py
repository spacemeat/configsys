import os

from configsys.componentObj import ResolvedComponent
from configsys.families import get_family
from configsys.families.dotfiles import DotFiles
from configsys.paths import Paths
from configsys.runner import Runner


def df_unit(specs=None, comp='neovim'):
    fields = specs if specs is not None else {
        'config': {'src': 'neovim', 'dst': '$XDG_CONFIG_HOME/nvim'}}
    return ResolvedComponent(key=f'dotfiles\\{comp}', family='dotfiles', comp=comp,
                             fields=fields)


def paths_for(tmp_path):
    return Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home'),
                      'CONFIGSYS_REPO': str(tmp_path / 'repo')})


def test_registry_has_dotfiles():
    assert isinstance(get_family('dotfiles', Runner(pretend=True)), DotFiles)


def test_single_inline_spec():
    rc = ResolvedComponent(key='dotfiles\\arduino', family='dotfiles', comp='arduino',
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
