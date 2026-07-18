'''fastfetch: native where packaged (Arch/Fedora/EL), and the official github .deb on
the apt driver (no Ubuntu / Debian<=12 has it), via the apt `deb` install mode.'''

import os

import humon

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver
from configsys.drivers.apt import Apt
from configsys.routes import Resolver
from configsys.runner import Runner

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')


def _resolve(block, ver):
    return Resolver(ROUTES, block, ver).resolve_names(['fastfetch'])


def test_routing_per_distro():
    assert 'apt\\fastfetch' in _resolve('pop_os!', '22.04')      # deb mode
    assert 'apt\\fastfetch' in _resolve('ubuntu', '24.04')
    assert 'dnf\\fastfetch' in _resolve('fedora', '41')          # native
    assert 'pacman\\fastfetch' in _resolve('arch', '20260712')   # native


def test_apt_uses_deb_mode_with_a_github_asset():
    rc = _resolve('pop_os!', '22.04')['apt\\fastfetch']
    assert rc.fields.get('deb-source') == 'github:fastfetch-cli/fastfetch'
    assert rc.fields['asset']['x86_64'] == 'fastfetch-linux-amd64.deb'
    assert rc.fields['asset']['aarch64'] == 'fastfetch-linux-aarch64.deb'


def test_el_fastfetch_pulls_epel():
    rc = _resolve('rhel', '9.8')['dnf\\fastfetch']
    assert 'dnf\\epel-release' in rc.deps


def _deb_unit():
    return ResolvedComponent(
        key='apt\\fastfetch', driver='apt', comp='fastfetch',
        fields={'name': 'fastfetch', 'deb-source': 'github:fastfetch-cli/fastfetch',
                'asset': {'x86_64': 'fastfetch-linux-amd64.deb',
                          'aarch64': 'fastfetch-linux-aarch64.deb'}})


def test_deb_install_downloads_asset_and_apt_installs(monkeypatch):
    r = Runner(pretend=True)
    fam = Apt(r)
    monkeypatch.setattr(fam, 'resolve_version', lambda rc: '2.66.0')
    monkeypatch.setattr(fam, 'download_url',
                        lambda rc, v: 'https://github.com/x/fastfetch-linux-amd64.deb')
    fam.install(_deb_unit())
    cmd = r.calls[-1]
    assert 'curl -fSL' in cmd and 'fastfetch-linux-amd64.deb' in cmd
    assert 'apt-get install -y /tmp/configsys-fastfetch.deb' in cmd
    assert '.deb' in cmd and cmd.startswith('sudo ')


def test_deb_get_latest_uses_version_spec_not_apt_cache(monkeypatch):
    fam = Apt(Runner(pretend=True))
    monkeypatch.setattr(fam, 'resolve_version', lambda rc: '2.66.0')
    assert fam.get_latest(_deb_unit()) == '2.66.0'


def test_deb_get_version_is_still_dpkg():
    # once installed the .deb registers as `fastfetch`; version comes from dpkg
    class FR:
        calls = []
        def run(self, cmd, **k):
            from configsys.runner import Result
            return Result(cmd, 0, stdout='2.66.0') if 'dpkg-query' in cmd else Result(cmd, 0)
    assert Apt(FR()).get_version(_deb_unit()) == '2.66.0'
