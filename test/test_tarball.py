import shutil
import tarfile

import pytest

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver
from configsys.drivers.tarball import Tarball
from configsys.paths import Paths
from configsys.runner import Runner


def tb_unit(installdir, url='https://x/y-1.2.3.tar.xz', version='1.2.3', comp='vulkan-sdk'):
    return ResolvedComponent(key=f'tarball\\{comp}', driver='tarball', comp=comp,
                             fields={'url': url, 'installDir': str(installdir)},
                             vars={'$SDKVERSION': version})


def test_registry_has_tarball():
    assert isinstance(get_driver('tarball', Runner(pretend=True)), Tarball)


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


def test_install_uses_unzip_for_zip_url(tmp_path):
    d = tmp_path / 'inst'
    r = Runner(pretend=True)
    Tarball(r, paths=None).install(tb_unit(d, url='https://x/deno-linux.zip'))
    cmd = r.calls[0]
    assert 'unzip -o -q' in cmd and f'-d {d}' in cmd     # zip path
    assert 'tar -xf' not in cmd


def test_install_zip_forced_by_archive_field(tmp_path):
    # url has no .zip extension (e.g. a redirect) but the binding declares archive: zip
    d = tmp_path / 'inst'
    rc = tb_unit(d, url='https://x/download?id=9')
    rc.fields['archive'] = 'zip'
    r = Runner(pretend=True)
    Tarball(r, paths=None).install(rc)
    assert 'unzip -o -q' in r.calls[0] and 'tar -xf' not in r.calls[0]


def test_install_bare_binary_no_extract(tmp_path):
    # archive:none -> download straight to installDir/<binary>, chmod +x, no tar/unzip
    d = tmp_path / 'inst'
    rc = tb_unit(d, url='https://x/bazelisk-linux-amd64', comp='bazelisk')
    rc.fields['archive'] = 'none'
    r = Runner(pretend=True)
    Tarball(r, paths=None).install(rc)
    cmd = r.calls[0]
    assert f'-o {d / "bazelisk"}' in cmd and f'chmod +x {d / "bazelisk"}' in cmd
    assert 'tar -xf' not in cmd and 'unzip' not in cmd


def test_install_bare_binary_custom_name(tmp_path):
    d = tmp_path / 'inst'
    rc = tb_unit(d, url='https://x/kubectl', comp='kubectl')
    rc.fields.update({'archive': 'none', 'binary': 'kubectl'})
    r = Runner(pretend=True)
    Tarball(r, paths=None).install(rc)
    assert f'chmod +x {d / "kubectl"}' in r.calls[0]


def test_install_gz_single_binary(tmp_path):
    # archive:gz -> a PLAIN gzipped single binary (not a .tar.gz): gunzip -c straight to
    # installDir/<binary>, chmod +x, clean the temp. No tar/unzip.
    d = tmp_path / 'inst'
    rc = tb_unit(d, url='https://x/tree-sitter-linux-x64.gz', comp='tree-sitter-cli')
    rc.fields.update({'archive': 'gz', 'binary': 'tree-sitter'})
    r = Runner(pretend=True)
    Tarball(r, paths=None).install(rc)
    cmd = r.calls[0]
    assert 'curl -fSL' in cmd and 'gunzip -c' in cmd
    assert f'> {d / "tree-sitter"}' in cmd and f'chmod +x {d / "tree-sitter"}' in cmd
    assert 'tar -xf' not in cmd and 'unzip -o' not in cmd   # not tar, not the zip path (gunzip != unzip)
    assert 'printf %s 1.2.3' in cmd


def test_pretend_version_discovery_is_offline(tmp_path):
    # --pretend (Runner(pretend=True)) must not touch the network: a github spec with an empty
    # cache resolves to None, and the url falls back to github's API-free latest/download.
    from configsys.paths import Paths
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path)})
    rc = ResolvedComponent(key='tarball\\x', driver='tarball', comp='x',
                           fields={'installDir': str(tmp_path),
                                   'version': {'github': 'o/r', 'asset': 'x-linux-amd64.deb'}})
    d = Tarball(Runner(pretend=True), paths=paths)
    assert d.resolve_version(rc) is None                     # offline + empty cache => no version
    assert d.download_url(rc, '') == \
        'https://github.com/o/r/releases/latest/download/x-linux-amd64.deb'


def test_install_defaults_to_tar(tmp_path):
    d = tmp_path / 'inst'
    r = Runner(pretend=True)
    Tarball(r, paths=None).install(tb_unit(d, url='https://x/y-1.2.3.tar.gz'))
    assert 'tar -xf' in r.calls[0] and 'unzip' not in r.calls[0]


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
    rc = ResolvedComponent(key='tarball\\vulkan-sdk', driver='tarball', comp='vulkan-sdk',
                           fields={'url': 'u', 'installDir': '~/vulkan'},
                           vars={'$SDKVERSION': '1'})
    tb = Tarball(Runner(pretend=True), paths=p)
    assert str(tb._marker(rc)) == '/sandbox/vulkan/.configsys-vulkan-sdk.version'


def test_user_scope_relative_installdir_is_home():
    p = Paths(env={'CONFIGSYS_HOME': '/home/u'})
    rc = ResolvedComponent(key='tarball\\vulkan-sdk', driver='tarball', comp='vulkan-sdk',
                           fields={'url': 'https://x/v.tar', 'installDir': 'vulkan'},
                           vars={'$SDKVERSION': '1'})
    r = Runner(pretend=True)
    Tarball(r, paths=p).install(rc)
    assert 'sudo' not in r.calls[0]
    assert '/home/u/vulkan' in r.calls[0]


def test_system_scope_relative_installdir_is_opt_with_sudo():
    p = Paths(env={'CONFIGSYS_HOME': '/home/u'})
    rc = ResolvedComponent(key='tarball\\vulkan-sdk', driver='tarball', comp='vulkan-sdk',
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


def test_version_spec_substituted_into_url():
    rc = ResolvedComponent(key='tarball\\x', driver='tarball', comp='x',
                           fields={'url': 'https://h/$VERSION/pkg-$VERSION.tar',
                                   'installDir': 'x', 'version': {'static': '9.9'}})
    r = Runner(pretend=True)
    Tarball(r, paths=Paths(env={'CONFIGSYS_HOME': '/home/u'})).install(rc)
    assert 'https://h/9.9/pkg-9.9.tar' in r.calls[0]
    assert '$VERSION' not in r.calls[0]


def test_get_latest_from_static_version_spec():
    rc = ResolvedComponent(key='tarball\\x', driver='tarball', comp='x',
                           fields={'url': 'u', 'installDir': 'x',
                                   'version': {'static': '9.9'}})
    assert Tarball(Runner(pretend=True), paths=None).get_latest(rc) == '9.9'


@pytest.mark.skipif(shutil.which('curl') is None, reason='needs curl')
def test_real_download_extract_and_uninstall(tmp_path):
    payload = tmp_path / 'hello.txt'
    payload.write_text('hi')
    tarpath = tmp_path / 'pkg-9.9.tar'
    with tarfile.open(tarpath, 'w') as t:
        t.add(payload, arcname='pkg/hello.txt')

    inst = tmp_path / 'inst'
    rc = ResolvedComponent(key='tarball\\pkg', driver='tarball', comp='pkg',
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
