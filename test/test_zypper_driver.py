'''The zypper driver (openSUSE / SUSE). RPM-based installed-version query like dnf; zypper for
everything else. Command construction is unit-tested here (pretend mode); live-box validation
is deferred — there is no openSUSE testbed yet.'''

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.zypper import Zypper
from configsys.runner import Result, Runner


def pkg(name='vim'):
    return ResolvedComponent(key=f'zypper\\{name}', driver='zypper', comp=name,
                             fields={'name': name})


class FakeRunner:
    def __init__(self, responses=None):
        self.responses = responses or []
        self.calls = []

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None, cwd=None, env=None):
        full = f'sudo {cmd}' if sudo else cmd
        self.calls.append(full)
        for needle, code, out in self.responses:
            if needle in cmd:
                return Result(full, code, stdout=out)
        return Result(full, 0, stdout='')


def test_registered_system_scoped():
    fam = get_driver('zypper', Runner(pretend=True))
    assert isinstance(fam, Zypper) and is_supported('zypper')
    assert fam.privileged and fam.default_scope == 'system' and not fam.honors_scope


def test_mutating_commands():
    r = Runner(pretend=True)
    d = Zypper(r)
    d.install(pkg()); d.uninstall(pkg()); d.upgrade(pkg())
    d.set_version(pkg(), '9.0.1-1.2'); d.lock(pkg()); d.unlock(pkg())
    assert r.calls == [
        'sudo zypper --non-interactive install vim',
        'sudo zypper --non-interactive remove vim',
        'sudo zypper --non-interactive update vim',
        'sudo zypper --non-interactive install --oldpackage vim=9.0.1-1.2',
        'sudo zypper --non-interactive addlock vim',
        'sudo zypper --non-interactive removelock vim',
    ]


def test_get_version_uses_rpm_query():
    fr = FakeRunner([('rpm -q', 0, '9.0.1\n')])
    assert Zypper(fr).get_version(pkg()) == '9.0.1'


def test_get_version_not_installed():
    fr = FakeRunner([('rpm -q', 1, 'package vim is not installed\n')])
    assert Zypper(fr).get_version(pkg()) is None


def test_get_latest_parses_info():
    info = 'Information for package vim:\nRepository     : Main\nName           : vim\nVersion        : 9.1.0-1.5\nArch           : x86_64\n'
    fr = FakeRunner([('zypper --terse --no-refresh info', 0, info)])
    assert Zypper(fr).get_latest(pkg()) == '9.1.0-1.5'


def test_is_locked_reads_locks_table():
    locks = '# | Name | Type    | Repository\n--+------+---------+-----------\n1 | vim  | package | (any)\n'
    assert Zypper(FakeRunner([('zypper --terse locks', 0, locks)])).is_locked(pkg()) is True
    # a different package held is not a match
    other = '1 | emacs | package | (any)\n'
    assert Zypper(FakeRunner([('zypper --terse locks', 0, other)])).is_locked(pkg()) is False
