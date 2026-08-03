'''fastfetch: native where the distro packages it (Arch/Fedora/EL); on Debian/Ubuntu (absent
from the repos through 22.04/24.04/bookworm) the official upstream .deb via the native-pkg-file
driver — a distinct, opt-in method from repo `native`.'''

import os

from configsys.componentObj import ResolvedComponent
from configsys.drivers.native_pkg_file import NativePkgFile
from configsys.routes import Resolver
from configsys.runner import Result, Runner

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')


def _resolve(block, ver):
    return Resolver(ROUTES, block, ver).resolve_names(['fastfetch'])


def test_routing_per_distro():
    assert 'native-pkg-file\\fastfetch' in _resolve('pop_os!', '22.04')   # upstream .deb
    assert 'native-pkg-file\\fastfetch' in _resolve('ubuntu', '24.04')
    assert 'dnf\\fastfetch' in _resolve('fedora', '41')                   # native repo
    assert 'pacman\\fastfetch' in _resolve('arch', '20260712')           # native repo


def test_debian_binding_carries_github_asset():
    rc = _resolve('pop_os!', '22.04')['native-pkg-file\\fastfetch']
    assert rc.fields['version'] == {'github': 'fastfetch-cli/fastfetch'}
    assert rc.fields['asset']['x86_64'] == 'fastfetch-linux-amd64.deb'
    assert rc.fields['asset']['aarch64'] == 'fastfetch-linux-aarch64.deb'


def test_el_fastfetch_pulls_epel():
    rc = _resolve('rhel', '9.8')['dnf\\fastfetch']
    assert 'dnf\\epel-release' in rc.deps


def _unit():
    return ResolvedComponent(
        key='native-pkg-file\\fastfetch', driver='native-pkg-file', comp='fastfetch',
        fields={'name': 'fastfetch', 'version': {'github': 'fastfetch-cli/fastfetch'},
                'asset': {'x86_64': 'fastfetch-linux-amd64.deb',
                          'aarch64': 'fastfetch-linux-aarch64.deb'}})


def _driver(runner, monkeypatch, fmt='deb'):
    d = NativePkgFile(runner)
    monkeypatch.setattr(d, '_format', lambda: fmt)
    return d


def test_install_downloads_asset_and_installs_with_the_pkg_tool(monkeypatch):
    r = Runner(pretend=True)
    d = _driver(r, monkeypatch)
    monkeypatch.setattr(d, 'resolve_version', lambda rc: '2.66.0')
    monkeypatch.setattr(d, 'download_url',
                        lambda rc, v: 'https://github.com/x/fastfetch-linux-amd64.deb')
    d.install(_unit())
    cmd = r.calls[-1]
    assert 'curl -fSL' in cmd and 'fastfetch-linux-amd64.deb' in cmd
    assert 'apt-get install -y' in cmd and '/tmp/configsys-fastfetch.pkg' in cmd
    assert cmd.startswith('sudo ')


def test_rpm_format_installs_with_dnf(monkeypatch):
    # the SAME binding on an rpm host installs the release package via dnf — one via, OS-dispatched
    r = Runner(pretend=True)
    d = _driver(r, monkeypatch, fmt='rpm')
    monkeypatch.setattr(d, 'resolve_version', lambda rc: '2.66.0')
    monkeypatch.setattr(d, 'download_url', lambda rc, v: 'https://github.com/x/fastfetch.rpm')
    d.install(_unit())
    assert 'dnf install -y' in r.calls[-1]


def test_get_latest_is_the_upstream_release(monkeypatch):
    d = _driver(Runner(pretend=True), monkeypatch)
    monkeypatch.setattr(d, 'resolve_version', lambda rc: '2.66.0')
    assert d.get_latest(_unit()) == '2.66.0'


def test_get_version_queries_the_os_db(monkeypatch):
    # once installed the .deb registers as `fastfetch`; version comes from dpkg-query
    class FR:
        def run(self, cmd, **k):
            return Result(cmd, 0, stdout='2.66.0\n') if 'dpkg-query' in cmd else Result(cmd, 0)
    d = NativePkgFile(FR())
    monkeypatch.setattr(d, '_format', lambda: 'deb')
    assert d.get_version(_unit()) == '2.66.0'
