from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.rpm_ostree import RpmOstree
from configsys.runner import Result, Runner


def pkg(name='akmod-nvidia', fields=None):
    f = {'name': name}
    f.update(fields or {})
    return ResolvedComponent(key=f'rpm-ostree\\{name}', driver='rpm-ostree', comp=name, fields=f)


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


def test_registered_privileged_system_scope():
    d = get_driver('rpm-ostree', Runner(pretend=True))
    assert isinstance(d, RpmOstree) and is_supported('rpm-ostree')
    assert d.privileged is True
    assert d.default_scope == 'system'
    assert RpmOstree.name == 'rpm-ostree'


def test_install_stages_by_default_under_sudo():
    r = Runner(pretend=True)
    RpmOstree(r).install(pkg('akmod-nvidia'))
    assert len(r.calls) == 1
    call = r.calls[0]
    assert call.startswith('sudo ')
    assert 'rpm-ostree install -y akmod-nvidia' in call
    assert '--apply-live' not in call
    assert 'staged' in call and 'reboot' in call


def test_install_apply_live_when_field_set():
    r = Runner(pretend=True)
    RpmOstree(r).install(pkg('vim', {'apply-live': True}))
    assert 'rpm-ostree install --apply-live -y vim' in r.calls[0]
    assert 'live' in r.calls[0]


def test_uninstall_stages_and_can_apply_live():
    r = Runner(pretend=True)
    RpmOstree(r).uninstall(pkg('vim'))
    RpmOstree(r).uninstall(pkg('vim', {'apply-live': 'yes'}))
    assert 'rpm-ostree uninstall -y vim' in r.calls[0] and '--apply-live' not in r.calls[0]
    assert 'rpm-ostree uninstall --apply-live -y vim' in r.calls[1]


def test_get_version_reads_running_rpm():
    fr = FakeRunner([("rpm -q --qf '%{VERSION}' htop", 0, '3.2.2')])
    assert RpmOstree(fr).get_version(pkg('htop')) == '3.2.2'


def test_get_version_absent_or_staged_reads_none():
    # rpm -q exits nonzero when the package isn't in the running system
    fr = FakeRunner([("rpm -q", 1, 'package htop is not installed')])
    assert RpmOstree(fr).get_version(pkg('htop')) is None


def test_latest_and_lock_are_honest_nots():
    d = RpmOstree(Runner(pretend=True))
    assert d.get_latest(pkg()) is None
    assert d.is_locked(pkg()) is False


def test_upgrade_setversion_lock_are_informational_noops():
    d = RpmOstree(Runner(pretend=True))
    for res in (d.upgrade(pkg()), d.set_version(pkg(), '1.2'),
                d.lock(pkg()), d.unlock(pkg())):
        assert res.ok                 # informational, not a hard failure
        # the explanatory message rides on Result.cmd (the cargo/ledger convention)
        assert 'rpm-ostree' in res.cmd.lower() or 'lock' in res.cmd.lower()
