'''review-2026-11-2 A6: one guard (Driver.unsafe_dir_reason / replace_dir_refusal) before every
rm -rf or mv-over of a "component's own" dir: never home, a scope base, a category dir, the state
dir or any ancestor of them, never a distro tree or a shared dir, never a dir configsys didn't
install (without --force); `locations:` must be absolute or ~-rooted, and ~ is configsys's home.'''

import pytest

from configsys import actions
from configsys.componentObj import ResolvedComponent
from configsys.driver import Driver
from configsys.drivers.appImage import AppImage
from configsys.drivers.font import Font
from configsys.drivers.tarball import Tarball
from configsys.paths import Paths
from configsys.runner import Runner


@pytest.fixture
def paths(tmp_path):
    return Paths(env={'CONFIGSYS_HOME': str(tmp_path / 'home')})


@pytest.mark.parametrize('rel', ['', 'apps', 'sdks', 'src', '.config', '.config/configsys', '.local/bin',
                                 '.local/share/fonts', '.ssh', 'Documents', 'apps/../..'])
def test_home_and_its_shared_dirs_are_never_removable(paths, rel):
    d = Driver(Runner(pretend=True), paths)
    assert d.unsafe_dir_reason(str(paths.home / rel) if rel else str(paths.home))


@pytest.mark.parametrize('p', ['/', '/opt', '/usr', '/usr/share', '/usr/local', '/usr/local/bin', '/etc/x',
                               '/var/lib/x', '/home/someone', 'relative/dir'])
def test_system_and_shared_dirs_are_never_removable(paths, p):
    assert Driver(Runner(pretend=True), paths).unsafe_dir_reason(p)


@pytest.mark.parametrize('rel', ['apps/zig', 'sdks/go', '.local/share/fonts/configsys-x'])
def test_a_components_own_dir_is_fine(paths, rel):
    assert Driver(Runner(pretend=True), paths).unsafe_dir_reason(str(paths.home / rel)) is None
    assert Driver(Runner(pretend=True), paths).unsafe_dir_reason('/opt/apps/zig') is None


def _tb(installdir):
    return ResolvedComponent(key='tarball\\zig', driver='tarball', comp='zig',
                             fields={'url': 'https://x/zig.tar', 'installDir': installdir,
                                     'version': {'static': '1'}})


@pytest.mark.parametrize('installdir', ['../home', '$CONFIGSYS_APP_DIR', '~/.config', '~/.ssh', '/usr/local/bin'])
def test_tarball_refuses_a_dangerous_install_dir(paths, installdir):
    r = Runner(pretend=True)
    res = Tarball(r, paths=paths).install(_tb(installdir))
    assert not res.ok and 'refusing' in res.output and not r.calls


def test_tarball_wont_replace_a_dir_it_didnt_install_without_force(paths):
    d = paths.home / 'apps' / 'zig'
    d.mkdir(parents=True)
    (d / 'zig').write_text('hand-installed')
    r = Runner(pretend=True)
    res = Tarball(r, paths=paths).install(_tb('$CONFIGSYS_APP_DIR/zig'))
    assert not res.ok and 'didn\'t install it' in res.output and not r.calls
    paths.install_force = True
    assert Tarball(r, paths=paths).install(_tb('$CONFIGSYS_APP_DIR/zig')).ok and r.calls


def test_font_locations_into_a_shared_dir_is_refused(paths):
    rc = ResolvedComponent(key='font\\x', driver='font', comp='x',
                           fields={'url': 'https://x/f.zip', 'version': {'static': '1'},
                                   'location-override': '~/.local/share/fonts'})
    r = Runner(pretend=True)
    assert not Font(r, paths=paths).install(rc).ok and not r.calls
    assert not Font(r, paths=paths).uninstall(rc).ok and not r.calls


def test_appimage_never_moves_over_your_shell_rc(paths):
    rc = ResolvedComponent(key='appImage\\x', driver='appImage', comp='x',
                           fields={'url': 'https://x/a', 'path': '~/.bashrc', 'version': {'static': '1'}})
    r = Runner(pretend=True)
    assert not AppImage(r, paths=paths).install(rc).ok and not r.calls


def test_locations_must_be_absolute_and_tilde_is_configsys_home(paths):
    with pytest.raises(ValueError, match='absolute'):
        actions._parse_map_tokens(['ripgrep=relative/rg'])
    assert actions._parse_map_tokens(['rg=/opt/x//rg']) == {'rg': '/opt/x/rg'}   # `//` normalized
    d = Driver(Runner(pretend=True), paths)
    got = d.location_override(ResolvedComponent(key='k', driver='tarball', comp='rg',
                                                fields={'location-override': '~/apps/rg'}))
    assert str(got) == str(paths.home / 'apps' / 'rg')                # never the process $HOME


def test_cabal_exe_is_a_name_never_a_path():
    from configsys.drivers.cabal import Cabal
    rc = ResolvedComponent(key='cabal\\x', driver='cabal', comp='x', fields={'exe': '../../.bashrc'})
    assert Cabal(Runner(pretend=True))._exe(rc) == '.bashrc'
