from configsys.componentObj import ResolvedComponent
from configsys.families import get_family, is_supported
from configsys.families.flatpak import Flatpak
from configsys.runner import Result, Runner


def fp(name='org.mozilla.firefox', hub='flathub', **extra):
    fields = {'hub': hub, 'name': name}
    fields.update(extra)
    return ResolvedComponent(key=f'flatpak\\{name}', family='flatpak', comp=name,
                             fields=fields)


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


REMOTE_ADD = ('flatpak remote-add --user --if-not-exists flathub '
              'https://dl.flathub.org/repo/flathub.flatpakrepo')


def test_registered_and_unprivileged():
    fam = get_family('flatpak', Runner(pretend=True))
    assert isinstance(fam, Flatpak)
    assert is_supported('flatpak')
    assert fam.privileged is False


def test_install_adds_remote_then_installs_user_scope():
    r = Runner(pretend=True)
    Flatpak(r).install(fp())
    assert r.calls == [REMOTE_ADD,
                       'flatpak install --user -y flathub org.mozilla.firefox']
    assert all('sudo' not in c for c in r.calls)


def test_uninstall_upgrade_commands():
    r = Runner(pretend=True)
    Flatpak(r).uninstall(fp())
    Flatpak(r).upgrade(fp())
    assert r.calls[0] == 'flatpak uninstall --user -y org.mozilla.firefox'
    assert r.calls[1] == REMOTE_ADD
    assert r.calls[2] == 'flatpak update --user -y org.mozilla.firefox'


def test_lock_unlock_use_mask():
    r = Runner(pretend=True)
    Flatpak(r).lock(fp())
    Flatpak(r).unlock(fp())
    assert r.calls == ['flatpak mask --user org.mozilla.firefox',
                       'flatpak mask --user --remove org.mozilla.firefox']


def test_set_version_pins_commit():
    r = Runner(pretend=True)
    Flatpak(r).set_version(fp(), 'deadbeef')
    assert r.calls == ['flatpak update --user -y --commit=deadbeef org.mozilla.firefox']


def test_hub_url_override():
    r = Runner(pretend=True)
    Flatpak(r).ensure_remote(fp(hub='myhub', **{'hub-url': 'https://x/y.flatpakrepo'}))
    assert r.calls == ['flatpak remote-add --user --if-not-exists myhub '
                       'https://x/y.flatpakrepo']


def test_unknown_hub_no_url_skips_remote_add():
    r = Runner(pretend=True)
    Flatpak(r).ensure_remote(fp(hub='mystery'))
    assert r.calls == []


def test_get_version_parses_info():
    info = ('Firefox\n          ID: org.mozilla.firefox\n'
            '     Version: 130.0\n      Commit: abcdef123\n')
    fr = FakeRunner([('flatpak info --user', 0, info)])
    assert Flatpak(fr).get_version(fp()) == '130.0'


def test_get_version_falls_back_to_commit():
    info = 'Some App\n      Commit: cafebabe0000\n'
    fr = FakeRunner([('flatpak info --user', 0, info)])
    assert Flatpak(fr).get_version(fp()) == 'cafebabe0000'


def test_get_version_not_installed():
    fr = FakeRunner([('flatpak info --user', 1, 'error: not installed')])
    assert Flatpak(fr).get_version(fp()) is None


def test_get_latest_deferred_none():
    assert Flatpak(Runner(pretend=True)).get_latest(fp()) is None


def test_is_locked_reads_mask_list():
    fr = FakeRunner([('flatpak mask --user', 0, 'org.mozilla.firefox\n')])
    assert Flatpak(fr).is_locked(fp('org.mozilla.firefox')) is True
    assert Flatpak(fr).is_locked(fp('com.google.Chrome')) is False
