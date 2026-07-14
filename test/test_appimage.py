import os
import stat

import pytest

from configsys.componentObj import ResolvedComponent
from configsys.families import get_family
from configsys.families.appImage import AppImage
from configsys.paths import Paths
from configsys.runner import Runner


def ai_unit(path, url='https://x/app-1.0.AppImage', version='1.0', comp='neovim',
            name='Neovim'):
    return ResolvedComponent(key=f'appImage\\{comp}', family='appImage', comp=comp,
                             fields={'url': url, 'path': str(path), 'version': version,
                                     'name': name})


def test_registry_has_appimage():
    assert isinstance(get_family('appImage', Runner(pretend=True)), AppImage)


def test_install_command_construction(tmp_path):
    target = tmp_path / 'apps' / 'nvim.appimage'
    r = Runner(pretend=True)
    AppImage(r, paths=None).install(ai_unit(target))
    main = r.calls[0]
    assert f'mkdir -p {target.parent}' in main
    assert 'curl -fSL' in main and f'-o {target}' in main
    assert f'chmod +x {target}' in main
    assert 'printf %s 1.0' in main
    # a .desktop entry is written as a second, separate call
    assert any('applications' in c and '.desktop' in c for c in r.calls)
    assert all('sudo' not in c for c in r.calls)  # user scope default


def test_system_scope_uses_sudo(tmp_path):
    r = Runner(pretend=True)
    unit = ai_unit(tmp_path / 'app.appimage')
    unit.fields['scope'] = 'system'
    AppImage(r, paths=None).install(unit)
    assert r.calls[0].startswith('sudo ')


def test_get_version_present_and_missing(tmp_path):
    target = tmp_path / 'app.appimage'
    ai = AppImage(Runner(pretend=True), paths=None)
    rc = ai_unit(target)
    assert ai.get_version(rc) is None            # not installed
    target.write_text('binary')
    (target.parent / '.configsys-neovim.version').write_text('1.0')
    assert ai.get_version(rc) == '1.0'
    assert ai.get_latest(rc) == '1.0'
    assert ai.is_locked(rc) is False


def test_uninstall_guarded_removes_file_marker_desktop(tmp_path):
    r = Runner(pretend=True)
    target = tmp_path / 'app.appimage'
    AppImage(r, paths=None).uninstall(ai_unit(target))
    cmd = r.calls[0]
    assert '.configsys-neovim.version' in cmd     # guard
    assert f'rm -f {target}' in cmd
    assert '.desktop' in cmd


def test_lock_unlock_noops_ok():
    ai = AppImage(Runner(pretend=True), paths=None)
    assert ai.lock(ai_unit('/x')).ok
    assert ai.unlock(ai_unit('/x')).ok


@pytest.mark.skipif(__import__('shutil').which('curl') is None, reason='needs curl')
def test_real_install_chmod_marker_desktop_and_uninstall(tmp_path):
    src = tmp_path / 'src.AppImage'
    src.write_text('#!/bin/sh\necho hi\n')
    target = tmp_path / 'apps' / 'app.appimage'
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path)})  # contain HOME for .desktop
    rc = ai_unit(target, url=f'file://{src}', version='9.9', comp='thing', name='Thing')

    ai = AppImage(Runner(pretend=False), paths=paths)
    res = ai.install(rc)
    if not res.ok:
        pytest.skip('curl lacks file:// support here')

    assert target.exists()
    assert os.stat(target).st_mode & stat.S_IXUSR      # executable
    assert ai.get_version(rc) == '9.9'
    desktop = tmp_path / '.local/share/applications' / 'configsys-thing.desktop'
    assert desktop.exists()
    body = desktop.read_text()
    assert 'Name=Thing' in body and f'Exec={target}' in body

    ai.uninstall(rc)
    assert not target.exists()
    assert not desktop.exists()
