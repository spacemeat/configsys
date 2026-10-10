'''The Void Linux (xbps) driver: pkgver parsing, the batched inspect (installed + repo candidates +
holds in three calls), holds, and the System Updates hooks. Output shapes copied from a real
void-glibc container.'''

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver
from configsys.drivers.xbps import Xbps, _split_pkgver, _version_from_pkgver
from configsys.runner import Result


def rc(name='curl'):
    return ResolvedComponent(key=f'xbps\\{name}', driver='xbps', comp=name, fields={})


class FakeRunner:
    def __init__(self, responses=None):
        self.responses = responses or []
        self.calls = []

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None, cwd=None, env=None, presudo=False):
        full = f'sudo {cmd}' if sudo else cmd
        self.calls.append(full)
        for needle, code, out in self.responses:
            if needle in cmd:
                return Result(full, code, stdout=out)
        return Result(full, 0, stdout='')


INSTALLED = ('ii acl-2.3.2_1                      Access Control List filesystem support\n'
             'ii gcc-fortran-14.2.1+20250405_4   GNU Compiler Collection - Fortran\n'
             'ii curl-8.20.0_1                    Client that groks URLs\n')
REMOTE = ('[-] 0ad-0.27.1_6                                       Historically-based RTS\n'
          '[*] curl-8.22.0_1                                      Client that groks URLs\n'
          '[-] gcc-fortran-14.2.1+20250405_4                      GNU Compiler Collection\n')


def test_registered():
    assert isinstance(get_driver('xbps', FakeRunner()), Xbps)


def test_pkgver_parsing_handles_hyphenated_names():
    assert _split_pkgver('gcc-fortran-14.2.1+20250405_4') == ('gcc-fortran', '14.2.1+20250405_4')
    assert _split_pkgver('not a pkgver') == (None, None)
    # `gcc` must not be satisfied by gcc-fortran's row
    assert _version_from_pkgver('gcc-fortran-14.2.1_4\n', 'gcc') is None
    assert _version_from_pkgver('curl-8.22.0_1\n', 'curl') == '8.22.0_1'


def test_batch_answers_reads_without_more_spawns():
    r = FakeRunner([('xbps-query -l', 0, INSTALLED), ('xbps-query -Rs', 0, REMOTE),
                    ('xbps-query -H', 0, 'curl-8.20.0_1\n')])
    d = Xbps(r)
    d.batch = d.batch_index([rc('curl'), rc('0ad')])
    n = len(r.calls)
    assert d.get_version(rc('curl')) == '8.20.0_1'
    assert d.get_latest(rc('curl')) == '8.22.0_1'
    assert d.get_latest(rc('gcc-fortran')) == '14.2.1+20250405_4'
    assert d.get_version(rc('0ad')) is None and d.get_latest(rc('0ad')) == '0.27.1_6'
    assert d.is_locked(rc('curl')) is True and d.is_locked(rc('acl')) is False
    assert len(r.calls) == n                       # all answered from the batch


def test_per_unit_fallbacks():
    r = FakeRunner([('-p pkgver curl', 0, 'curl-8.22.0_1\n'), ('-p hold curl', 0, 'yes\n')])
    d = Xbps(r)
    assert d.get_version(rc('curl')) == '8.22.0_1'
    assert d.get_latest(rc('curl')) == '8.22.0_1'
    assert 'xbps-query -R -p pkgver curl' in r.calls[-1]
    assert d.is_locked(rc('curl')) is True


def test_mutations_use_sudo_and_holds():
    r = FakeRunner()
    d = Xbps(r)
    d.install(rc('curl'))
    d.uninstall(rc('curl'))
    d.lock(rc('curl'))
    d.unlock(rc('curl'))
    assert r.calls == ['sudo xbps-install -Sy curl', 'sudo xbps-remove -y curl',
                       'sudo xbps-pkgdb -m hold curl', 'sudo xbps-pkgdb -m unhold curl']


def test_upgradable_index_keeps_only_updates():
    r = FakeRunner([
        ('xbps-install -un', 0,
         'acl-2.4.0_1 update x86_64 https://repo-default.voidlinux.org/current 43080 20653\n'
         'libnew-1.0_1 install x86_64 https://repo-default.voidlinux.org/current 1 1\n'),
        ('xbps-query -l', 0, INSTALLED)])
    assert Xbps(r).upgradable_index() == {'acl': ('2.3.2_1', '2.4.0_1')}
