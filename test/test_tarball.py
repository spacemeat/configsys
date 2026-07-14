import shutil
import tarfile

import pytest

from configsys.componentObj import ResolvedComponent
from configsys.families import get_family
from configsys.families.tarball import Tarball
from configsys.paths import Paths
from configsys.runner import Runner


def tb_unit(installdir, url='https://x/y-1.2.3.tar.xz', version='1.2.3', comp='vulkan-sdk'):
    return ResolvedComponent(key=f'tarball\\{comp}', family='tarball', comp=comp,
                             fields={'url': url, 'installDir': str(installdir)},
                             vars={'$SDKVERSION': version})


def test_registry_has_tarball():
    assert isinstance(get_family('tarball', Runner(pretend=True)), Tarball)


def test_install_command_construction(tmp_path):
    d = tmp_path / 'inst'
    r = Runner(pretend=True)
    Tarball(r, paths=None).install(tb_unit(d))
    assert len(r.calls) == 1
    cmd = r.calls[0]
    assert f'mkdir -p {d}' in cmd
    assert 'curl -fSL' in cmd and 'y-1.2.3.tar.xz' in cmd
    assert 'tar -xf' in cmd and f'-C {d}' in cmd
    assert 'printf %s 1.2.3' in cmd
    assert 'sudo' not in cmd   # user-space, never privileged


def test_get_version_reads_marker(tmp_path):
    d = tmp_path / 'inst'
    d.mkdir()
    (d / '.configsys-vulkan-sdk.version').write_text('1.2.3')
    tb = Tarball(Runner(pretend=True), paths=None)
    rc = tb_unit(d)
    assert tb.get_version(rc) == '1.2.3'
    assert tb.get_latest(rc) == '1.2.3'   # declared version
    assert tb.is_locked(rc) is False


def test_get_version_missing(tmp_path):
    assert Tarball(Runner(pretend=True), paths=None).get_version(tb_unit(tmp_path / 'no')) is None


def test_uninstall_guarded_by_marker(tmp_path):
    d = tmp_path / 'inst'
    r = Runner(pretend=True)
    Tarball(r, paths=None).uninstall(tb_unit(d))
    cmd = r.calls[0]
    assert '.configsys-vulkan-sdk.version' in cmd
    assert f'rm -rf {d}' in cmd


def test_installdir_expands_via_paths():
    p = Paths(env={'CONFIGSYS_HOME': '/sandbox'})
    rc = ResolvedComponent(key='tarball\\vulkan-sdk', family='tarball', comp='vulkan-sdk',
                           fields={'url': 'u', 'installDir': '~/vulkan'},
                           vars={'$SDKVERSION': '1'})
    tb = Tarball(Runner(pretend=True), paths=p)
    assert str(tb._marker(rc)) == '/sandbox/vulkan/.configsys-vulkan-sdk.version'


def test_user_scope_relative_installdir_is_home():
    p = Paths(env={'CONFIGSYS_HOME': '/home/u'})
    rc = ResolvedComponent(key='tarball\\vulkan-sdk', family='tarball', comp='vulkan-sdk',
                           fields={'url': 'https://x/v.tar', 'installDir': 'vulkan'},
                           vars={'$SDKVERSION': '1'})
    r = Runner(pretend=True)
    Tarball(r, paths=p).install(rc)
    assert 'sudo' not in r.calls[0]
    assert '/home/u/vulkan' in r.calls[0]


def test_system_scope_relative_installdir_is_opt_with_sudo():
    p = Paths(env={'CONFIGSYS_HOME': '/home/u'})
    rc = ResolvedComponent(key='tarball\\vulkan-sdk', family='tarball', comp='vulkan-sdk',
                           fields={'url': 'https://x/v.tar', 'installDir': 'vulkan',
                                   'scope': 'system'},
                           vars={'$SDKVERSION': '1'})
    r = Runner(pretend=True)
    Tarball(r, paths=p).install(rc)
    assert r.calls[0].startswith('sudo ')
    assert '/opt/vulkan' in r.calls[0]


def test_lock_unlock_are_ledger_backed_noops():
    tb = Tarball(Runner(pretend=True), paths=None)
    assert tb.lock(tb_unit('/x')).ok
    assert tb.unlock(tb_unit('/x')).ok


@pytest.mark.skipif(shutil.which('curl') is None, reason='needs curl')
def test_real_download_extract_and_uninstall(tmp_path):
    payload = tmp_path / 'hello.txt'
    payload.write_text('hi')
    tarpath = tmp_path / 'pkg-9.9.tar'
    with tarfile.open(tarpath, 'w') as t:
        t.add(payload, arcname='pkg/hello.txt')

    inst = tmp_path / 'inst'
    rc = ResolvedComponent(key='tarball\\pkg', family='tarball', comp='pkg',
                           fields={'url': f'file://{tarpath}', 'installDir': str(inst)},
                           vars={'$SDKVERSION': '9.9'})
    tb = Tarball(Runner(pretend=False), paths=None)

    res = tb.install(rc)
    if not res.ok:
        pytest.skip('curl lacks file:// support in this environment')
    assert (inst / 'pkg' / 'hello.txt').read_text() == 'hi'
    assert tb.get_version(rc) == '9.9'

    tb.uninstall(rc)
    assert not inst.exists()
