import shutil
import zipfile

import pytest

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver
from configsys.drivers.font import Font
from configsys.paths import Paths
from configsys.runner import Runner


def font_unit(url='https://x/F.zip', version='v1.0', comp='mononoki-nerd', scope=None):
    fields = {'name': 'Mononoki', 'url': url, 'version': {'static': version}}
    if scope:
        fields['scope'] = scope
    return ResolvedComponent(key=f'font\\{comp}', driver='font', comp=comp,
                             fields=fields)


def test_registry_has_font():
    assert isinstance(get_driver('font', Runner(pretend=True)), Font)


def test_install_command_construction(tmp_path):
    r = Runner(pretend=True)
    p = Paths(env={'CONFIGSYS_HOME': str(tmp_path)})
    Font(r, paths=p).install(font_unit())
    cmd = r.calls[0]
    fdir = tmp_path / '.local/share/fonts/configsys-mononoki-nerd'
    assert 'curl -fSL https://x/F.zip' in cmd
    assert f'mkdir -p {fdir}' in cmd
    assert '*.[to]tf' in cmd            # extracts ttf + otf in one glob
    assert 'printf %s v1.0' in cmd
    assert 'fc-cache' in cmd
    assert 'sudo' not in cmd            # user scope default


def test_system_scope_uses_opt_dir_and_sudo(tmp_path):
    r = Runner(pretend=True)
    p = Paths(env={'CONFIGSYS_HOME': str(tmp_path)})
    Font(r, paths=p).install(font_unit(scope='system'))
    cmd = r.calls[0]
    assert cmd.startswith('sudo ')
    assert '/usr/local/share/fonts/configsys-mononoki-nerd' in cmd


def test_uninstall_guarded_by_marker(tmp_path):
    r = Runner(pretend=True)
    p = Paths(env={'CONFIGSYS_HOME': str(tmp_path)})
    Font(r, paths=p).uninstall(font_unit())
    cmd = r.calls[0]
    assert '.configsys-mononoki-nerd.version' in cmd
    assert 'rm -rf' in cmd and 'fc-cache' in cmd


def test_get_latest_and_version(tmp_path):
    p = Paths(env={'CONFIGSYS_HOME': str(tmp_path)})
    fam = Font(Runner(pretend=True), paths=p)
    rc = font_unit(version='v2.5')
    assert fam.get_latest(rc) == 'v2.5'    # static discovery spec
    assert fam.get_version(rc) is None     # not installed
    assert fam.is_locked(rc) is False


@pytest.mark.skipif(shutil.which('unzip') is None or shutil.which('curl') is None,
                    reason='needs unzip + curl')
def test_real_install_extract_marker_uninstall(tmp_path):
    # build a real zip containing a fake .ttf
    zpath = tmp_path / 'F.zip'
    with zipfile.ZipFile(zpath, 'w') as z:
        z.writestr('Mononoki/Mononoki.ttf', b'\x00\x01ttf-bytes')
    p = Paths(env={'CONFIGSYS_HOME': str(tmp_path)})
    rc = font_unit(url=f'file://{zpath}', version='v9.9')

    fam = Font(Runner(pretend=False), paths=p)
    assert fam.install(rc).ok
    fdir = tmp_path / '.local/share/fonts/configsys-mononoki-nerd'
    assert (fdir / 'Mononoki.ttf').exists()          # extracted flat (-j)
    assert fam.get_version(rc) == 'v9.9'

    fam.uninstall(rc)
    assert not fdir.exists()
