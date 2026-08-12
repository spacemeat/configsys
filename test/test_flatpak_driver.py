from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.flatpak import Flatpak
from configsys.runner import Result, Runner


def fp(name='org.mozilla.firefox', hub='flathub', **extra):
    fields = {'hub': hub, 'name': name}
    fields.update(extra)
    return ResolvedComponent(key=f'flatpak\\{name}', driver='flatpak', comp=name,
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
    fam = get_driver('flatpak', Runner(pretend=True))
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
    fr = FakeRunner([('flatpak info', 0, info)])
    assert Flatpak(fr).get_version(fp()) == '130.0'


def test_get_version_falls_back_to_commit():
    info = 'Some App\n      Commit: cafebabe0000\n'
    fr = FakeRunner([('flatpak info', 0, info)])
    assert Flatpak(fr).get_version(fp()) == 'cafebabe0000'


def test_get_version_not_installed():
    fr = FakeRunner([('flatpak info', 1, 'error: not installed')])
    assert Flatpak(fr).get_version(fp()) is None


_REMOTE_INFO = 'ID: org.mozilla.firefox\nVersion: 4.0.0\nCommit: cafebabe0000\n'


def test_get_latest_parses_remote_info_version():
    fr = FakeRunner([('remote-info --user', 0, _REMOTE_INFO)])
    assert Flatpak(fr).get_latest(fp()) == '4.0.0'


def test_get_latest_falls_back_user_to_system():
    # the remote can live in both installations; --user failing must not stop us trying --system.
    fr = FakeRunner([('remote-info --user', 1, 'error'),
                     ('remote-info --system', 0, _REMOTE_INFO)])
    assert Flatpak(fr).get_latest(fp()) == '4.0.0'
    assert any('remote-info --system' in c for c in fr.calls)


def test_get_latest_none_without_version_field():
    # a bare commit hash isn't version-comparable -> None (unlike get_version, which shows it)
    fr = FakeRunner([('remote-info', 0, 'ID: x\nCommit: deadbeef\n')])
    assert Flatpak(fr).get_latest(fp()) is None


def test_get_latest_none_without_hub():
    rc = fp()
    rc.fields.pop('hub')
    assert Flatpak(FakeRunner([])).get_latest(rc) is None


def test_get_version_detects_system_install_under_default_user_scope():
    # regression: chrome installed system-wide must not read as "missing" just
    # because the route defaults to --user. `flatpak info` (no flag) finds either.
    info = ('Google Chrome\n          ID: com.google.Chrome\n'
            '     Version: 148.0.7778.215-1\n Installation: system\n')
    fr = FakeRunner([('flatpak info', 0, info)])
    rc = fp('com.google.Chrome')            # no scope field -> defaults to user
    assert Flatpak(fr).get_version(rc) == '148.0.7778.215-1'
    assert fr.calls == ['flatpak info com.google.Chrome']  # no --user flag


def test_get_latest_deferred_none():
    assert Flatpak(Runner(pretend=True)).get_latest(fp()) is None


def test_is_locked_reads_mask_list():
    fr = FakeRunner([('flatpak mask --user', 0, 'org.mozilla.firefox\n')])
    assert Flatpak(fr).is_locked(fp('org.mozilla.firefox')) is True
    assert Flatpak(fr).is_locked(fp('com.google.Chrome')) is False


# -- scope (user vs system) ----------------------------------------------

def test_system_scope_install_uses_sudo_and_system_flag():
    r = Runner(pretend=True)
    Flatpak(r).install(fp(scope='system'))
    assert r.calls == [
        'sudo flatpak remote-add --system --if-not-exists flathub '
        'https://dl.flathub.org/repo/flathub.flatpakrepo',
        'sudo flatpak install --system -y flathub org.mozilla.firefox',
    ]


def test_system_scope_uninstall_and_lock_sudo():
    r = Runner(pretend=True)
    Flatpak(r).uninstall(fp(scope='system'))
    Flatpak(r).lock(fp(scope='system'))
    assert r.calls == [
        'sudo flatpak uninstall --system -y org.mozilla.firefox',
        'sudo flatpak mask --system org.mozilla.firefox',
    ]


def test_read_ops_never_sudo_even_in_system_scope():
    fr = FakeRunner([('flatpak info', 0, 'Version: 1.0\n')])
    Flatpak(fr).get_version(fp(scope='system'))
    assert fr.calls == ['flatpak info org.mozilla.firefox']  # scope-agnostic, no sudo


def test_user_scope_is_the_default():
    r = Runner(pretend=True)
    Flatpak(r).install(fp())  # no scope field
    assert '--user' in r.calls[-1] and 'sudo' not in r.calls[-1]


def test_per_component_scope_from_route_is_honored():
    # a `scope` field on the component's binding drives the driver (component field wins);
    # absent, it defaults to --user.
    a = fp(name='com.a', scope='system')
    b = fp(name='com.b')
    assert a.fields.get('scope') == 'system'
    assert 'scope' not in b.fields

    r = Runner(pretend=True)
    Flatpak(r).install(a)
    Flatpak(r).install(b)
    app_calls = [c for c in r.calls if 'flatpak install' in c]
    assert app_calls == [
        'sudo flatpak install --system -y flathub com.a',
        'flatpak install --user -y flathub com.b',
    ]


def test_batch_index_collapses_probes_and_read_ops_use_it():
    # startup-perf Phase B: N flatpak units on one hub cost ONE `remote-ls` (all of the remote), not
    # a ~2s `remote-info` per app; plus one `flatpak list` and one `mask` per installation.
    r = FakeRunner([
        ('flatpak list --app', 0, 'org.blender.Blender\t4.3.0\tuser\n'),
        ('flatpak mask', 0, ''),
        ('flatpak remote-ls', 0, 'org.blender.Blender\t5.2\norg.gimp.GIMP\t3.2\n'),
    ])
    d = Flatpak(r)
    d._batch = d.batch_index([fp('org.blender.Blender'), fp('org.gimp.GIMP')])   # both flathub
    assert sum('remote-ls' in c for c in r.calls) == 1              # one per shared hub, not per app
    assert sum('flatpak list --app' in c for c in r.calls) == 1
    assert sum('remote-info' in c for c in r.calls) == 0           # the per-app path is skipped
    # read ops answer from the batch, no further spawns
    assert d.get_version(fp('org.blender.Blender')) == '4.3.0'
    assert d.get_installed(fp('org.blender.Blender')) == ('4.3.0', 'user')
    assert d.get_latest(fp('org.blender.Blender')) == '5.2'
    assert d.get_latest(fp('org.gimp.GIMP')) == '3.2'
    assert d.get_version(fp('org.gimp.GIMP')) is None              # not installed -> absent from list
