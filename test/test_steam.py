'''Steam: hybrid install method — native apt on Pop!_OS (the NVIDIA rig), flatpak
everywhere else — via the \\app method-selection mechanism, plus the apt family's
i386 multiarch prereq.'''

import os

import humon

from configsys.componentObj import ResolvedComponent
from configsys.families.apt import Apt
from configsys.routes import Resolver
from configsys.runner import Runner

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')


def _resolve(block, ver, name='steam'):
    return Resolver(ROUTES, block, ver).resolve_names([name])


def test_steam_native_apt_on_pop():
    units = _resolve('pop_os!', '22.04')
    rc = units['apt\\steam']
    assert rc.fields['name'] == 'steam:i386'          # Pop ships it as a 32-bit pkg
    assert rc.fields['foreign-arch'] == 'i386'


def test_steam_flatpak_everywhere_else():
    for block, ver in [('ubuntu', '24.04'), ('fedora', '41'), ('arch', '20260712')]:
        units = _resolve(block, ver)
        assert 'apt\\steam' not in units
        rc = units['flatpak\\steam']
        assert rc.fields['name'] == 'com.valvesoftware.Steam'


def test_steam_flatpak_pulls_the_flatpak_tool_per_distro():
    assert 'apt\\flatpak' in _resolve('ubuntu', '24.04')['flatpak\\steam'].deps
    assert 'dnf\\flatpak' in _resolve('fedora', '41')['flatpak\\steam'].deps
    assert 'pacman\\flatpak' in _resolve('arch', '20260712')['flatpak\\steam'].deps


def test_apt_foreign_arch_prereq_enables_i386_idempotently():
    r = Runner(pretend=True)
    rc = ResolvedComponent(key='apt\\steam', family='apt', comp='steam',
                           fields={'name': 'steam:i386', 'foreign-arch': 'i386'})
    Apt(r).install(rc)
    calls = ' ;; '.join(r.calls)
    # idempotence guard + enablement + refresh, then the arch-qualified install
    assert 'dpkg --print-foreign-architectures | grep -qx i386' in calls
    assert 'dpkg --add-architecture i386 && apt-get update' in calls
    assert 'apt-get install -y steam:i386' in calls


def test_apt_no_foreign_arch_when_unset():
    r = Runner(pretend=True)
    rc = ResolvedComponent(key='apt\\btop', family='apt', comp='btop',
                           fields={'name': 'btop'})
    Apt(r).install(rc)
    assert not any('add-architecture' in c for c in r.calls)
