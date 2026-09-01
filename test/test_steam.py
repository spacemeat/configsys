'''Steam: native wherever it's packaged — apt with i386 multiarch (Pop keeps its known-good
`steam:i386`; other Debian/Ubuntu use `steam-installer` from multiverse/non-free), Arch multilib,
Fedora RPM Fusion nonfree, openSUSE — with Flathub as the universal fallback where native can't
work (Alpine[musl] / atomic / EL). Plus the apt driver's i386 multiarch prereq.'''

import os

from configsys.componentObj import ResolvedComponent
from configsys.drivers.apt import Apt
from configsys.routes import Resolver
from configsys.runner import Runner

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')


def _resolve(block, ver=None, name='steam'):
    return Resolver(ROUTES, block, ver).resolve_names([name])


def test_steam_native_apt_on_pop():
    units = _resolve('pop_os!', '22.04')
    rc = units['apt\\steam']
    assert rc.fields['name'] == 'steam:i386'          # Pop ships it as a 32-bit pkg
    assert rc.fields['foreign-arch'] == 'i386'


def test_steam_native_where_packaged():
    # native is the default wherever steam is in-repo; flatpak is only the fallback (not resolved).
    for block, ver, drv in [('ubuntu', '24.04', 'apt'), ('debian', '12', 'apt'),
                            ('fedora', '41', 'dnf'), ('arch', '20260712', 'pacman'),
                            ('opensuse', None, 'zypper')]:
        units = _resolve(block, ver)
        assert f'{drv}\\steam' in units
        assert 'flatpak\\steam' not in units


def test_steam_ubuntu_uses_installer_i386_multiverse():
    rc = _resolve('ubuntu', '24.04')['apt\\steam']
    assert rc.fields['name'] == 'steam-installer'      # the modern multiverse metapackage
    assert rc.fields['foreign-arch'] == 'i386'
    assert rc.fields['repo-component'] == 'multiverse'


def test_steam_fedora_pulls_rpmfusion_nonfree():
    units = _resolve('fedora', '41')
    assert 'dnf\\steam' in units
    assert any('rpmfusion-nonfree' in k for k in units)   # nonfree repo pulled as a hard require


def test_steam_flatpak_fallback_where_native_absent():
    # Alpine (musl, no 32-bit glibc) and EL have no native steam -> Flathub, which pulls the
    # flatpak tool for that distro.
    for block, ver, drv in [('alpine', None, 'apk'), ('rhel', '9.8', 'dnf')]:
        rc = _resolve(block, ver)['flatpak\\steam']
        assert rc.fields['name'] == 'com.valvesoftware.Steam'
        assert f'{drv}\\flatpak' in rc.deps


def test_apt_foreign_arch_prereq_enables_i386_idempotently():
    r = Runner(pretend=True)
    rc = ResolvedComponent(key='apt\\steam', driver='apt', comp='steam',
                           fields={'name': 'steam:i386', 'foreign-arch': 'i386'})
    Apt(r).install(rc)
    calls = ' ;; '.join(r.calls)
    # idempotence guard + enablement + refresh, then the arch-qualified install
    assert 'dpkg --print-foreign-architectures | grep -qx i386' in calls
    assert 'dpkg --add-architecture i386 && apt-get update' in calls
    assert 'apt-get install -y steam:i386' in calls


def test_apt_no_foreign_arch_when_unset():
    r = Runner(pretend=True)
    rc = ResolvedComponent(key='apt\\btop', driver='apt', comp='btop',
                           fields={'name': 'btop'})
    Apt(r).install(rc)
    assert not any('add-architecture' in c for c in r.calls)
