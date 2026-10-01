'''A native binding's `packages: [...]` set is honored by EVERY native package manager, not just apt:
install/remove/upgrade act on the whole set, and detection reads one representative package
(`installed-name:`, else the first of the set) — never the unit's own name (`python-build-deps` is not
a package, so before this the non-apt managers tried to install it literally and never saw it).'''

import pytest

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver
from configsys.runner import Result


class FakeRunner:
    def __init__(self):
        self.calls = []

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None, cwd=None, env=None, presudo=False):
        self.calls.append(cmd)
        return Result(cmd, 0, stdout='')


def unit(driver, **fields):
    return ResolvedComponent(key=f'{driver}\\python-build-deps', driver=driver,
                             comp='python-build-deps', fields={'name': 'python-build-deps', **fields})


@pytest.mark.parametrize('driver', ['apt', 'dnf', 'pacman', 'zypper', 'apk', 'xbps'])
def test_packages_set_installs_whole_set_and_probes_first(driver):
    r = FakeRunner()
    d = get_driver(driver, r)
    u = unit(driver, packages=['gcc', 'make', 'zlib-devel'])
    d.install(u)
    assert any('gcc make zlib-devel' in c for c in r.calls), r.calls
    assert not any('python-build-deps' in c for c in r.calls)
    assert d.index_key(u) == 'gcc'


@pytest.mark.parametrize('driver', ['dnf', 'pacman', 'zypper', 'apk', 'xbps'])
def test_installed_name_wins_for_detection(driver):
    d = get_driver(driver, FakeRunner())
    assert d.index_key(unit(driver, packages=['a', 'b'], **{'installed-name': 'b'})) == 'b'
    plain = ResolvedComponent(key=f'{driver}\\curl', driver=driver, comp='curl', fields={'name': 'curl'})
    assert d.index_key(plain) == 'curl'
