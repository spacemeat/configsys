from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.dnf import Dnf
from configsys.runner import Result, Runner


def pkg(name='btop'):
    return ResolvedComponent(key=f'dnf\\{name}', driver='dnf', comp=name,
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
    fam = get_driver('dnf', Runner(pretend=True))
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


def test_vendor_repo_prereqs_before_install():
    # a third-party repo (e.g. Microsoft's vscode): import the key, drop a .repo file,
    # then install. The .repo write is idempotent (guarded on the file existing).
    comp = ResolvedComponent(key='dnf\\vscode', driver='dnf', comp='vscode', fields={
        'name': 'code',
        'pubkey-url': 'https://packages.microsoft.com/keys/microsoft.asc',
        'repo-id': 'code', 'repo-name': 'Visual Studio Code',
        'repo-url': 'https://packages.microsoft.com/yumrepos/vscode'})
    r = Runner(pretend=True)
    Dnf(r).install(comp)
    assert r.calls[0] == 'sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc'
    assert r.calls[-1] == 'sudo dnf install -y code'
    repo_write = next(c for c in r.calls if '/etc/yum.repos.d/code.repo' in c)
    assert 'baseurl=https://packages.microsoft.com/yumrepos/vscode' in repo_write
    assert '[code]' in repo_write and 'gpgcheck=1' in repo_write


def test_templated_gpgkey_is_left_for_dnf_not_imported_eagerly():
    # RPM Fusion's per-release key URL carries dnf repo vars ($releasever); `rpm --import`
    # can't expand them, so the key must NOT be imported up front — it's left in the .repo's
    # gpgkey= for dnf to expand + auto-import on the -y install.
    comp = ResolvedComponent(key='dnf\\rpmfusion-free', driver='dnf', comp='rpmfusion-free',
        fields={
            'name': 'rpmfusion-free-release',
            'repo-id': 'rpmfusion-free', 'repo-name': 'RPM Fusion Free',
            'repo-url': 'https://download1.rpmfusion.org/free/fedora/releases/$releasever/Everything/$basearch/os/',
            'pubkey-url': 'https://rpmfusion.org/keys?target=RPM-GPG-KEY-rpmfusion-free-fedora-$releasever'})
    r = Runner(pretend=True)
    Dnf(r).install(comp)
    assert not any('rpm --import' in c for c in r.calls)      # templated key: not eager
    repo_write = next(c for c in r.calls if '/etc/yum.repos.d/rpmfusion-free.repo' in c)
    assert 'gpgkey=https://rpmfusion.org/keys?target=' in repo_write   # left for dnf
    assert '$releasever' in repo_write and '$basearch' in repo_write
    assert r.calls[-1] == 'sudo dnf install -y rpmfusion-free-release'


def test_no_repo_prereqs_for_a_plain_package():
    r = Runner(pretend=True)
    Dnf(r).install(pkg())            # no repo-id/pubkey -> straight install
    assert r.calls == ['sudo dnf install -y btop']


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
