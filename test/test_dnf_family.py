from configsys.componentObj import ResolvedComponent
from configsys.families import get_family, is_supported
from configsys.families.dnf import Dnf
from configsys.runner import Result, Runner


def pkg(name='btop'):
    return ResolvedComponent(key=f'dnf\\{name}', family='dnf', comp=name,
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
    fam = get_family('dnf', Runner(pretend=True))
    assert isinstance(fam, Dnf) and is_supported('dnf')
    assert fam.privileged and fam.default_scope == 'system' and not fam.honors_scope


def test_install_uninstall_upgrade_commands():
    r = Runner(pretend=True)
    Dnf(r).install(pkg())
    Dnf(r).uninstall(pkg())
    Dnf(r).upgrade(pkg())
    assert r.calls == [
        'sudo dnf install -y btop',
        'sudo dnf remove -y btop',
        'sudo dnf upgrade -y btop',
    ]


def test_set_version_falls_back_to_downgrade():
    r = Runner(pretend=True)
    Dnf(r).set_version(pkg(), '1.4.3')
    assert r.calls == ['sudo dnf install -y btop-1.4.3 || dnf downgrade -y btop-1.4.3']


def test_get_version_parses_rpm_query():
    fr = FakeRunner([('rpm -q', 0, '1.4.4\n')])
    assert Dnf(fr).get_version(pkg()) == '1.4.4'


def test_get_version_not_installed():
    fr = FakeRunner([('rpm -q', 1, 'package btop is not installed\n')])
    assert Dnf(fr).get_version(pkg()) is None


def test_get_latest_from_repoquery():
    fr = FakeRunner([('dnf -q repoquery', 0, '1.4.4')])
    assert Dnf(fr).get_latest(pkg()) == '1.4.4'


def test_lock_installs_plugin_then_adds_versionlock():
    r = Runner(pretend=True)
    Dnf(r).lock(pkg())
    assert r.calls == [
        'sudo dnf install -y python3-dnf-plugin-versionlock',
        'sudo dnf versionlock add btop',
    ]


def test_unlock_deletes_versionlock():
    r = Runner(pretend=True)
    Dnf(r).unlock(pkg())
    assert r.calls[-1] == 'sudo dnf versionlock delete btop'


def test_is_locked_reads_dnf5_list_format():
    listing = ("# Added by 'versionlock add' command on 2026-07-15\n"
               'Package name: btop\nevr = 1.4.4-1.fc41\n')
    fr = FakeRunner([('dnf versionlock list', 0, listing)])
    assert Dnf(fr).is_locked(pkg('btop')) is True
    assert Dnf(fr).is_locked(pkg('ripgrep')) is False


def test_is_locked_false_when_plugin_absent():
    fr = FakeRunner([('dnf versionlock list', 1, 'Missing command.')])
    assert Dnf(fr).is_locked(pkg()) is False
