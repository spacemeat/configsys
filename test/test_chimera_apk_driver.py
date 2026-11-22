'''The chimera-apk driver (configsys/drivers/chimera_apk.py): Alpine's apk driver with Chimera's
differences — its own `via:` (so Chimera names never collide with Alpine's `apk:` names), the `user`
repository enabled once before the first install, `--no-interactive` mutations (Chimera's apk config
turns on a Y/n prompt), and the repo package kept out of the orphan scan's explicit set.'''

from configsys.componentObj import ResolvedComponent
from configsys.drivers import BUILTIN_DRIVERS, get_driver
from configsys.drivers.apk import Apk
from configsys.drivers.chimera_apk import ChimeraApk

from fakes import FakeRunner


def _rc(name='bat'):
    return ResolvedComponent(key=f'chimera-apk\\{name}', driver='chimera-apk', comp=name,
                             fields={'name': name})


class Notes(FakeRunner):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.notes = []

    def echo(self, msg):
        self.notes.append(msg)


def test_it_is_its_own_registered_via_sharing_apks_reads():
    assert 'chimera-apk' in BUILTIN_DRIVERS
    d = get_driver('chimera-apk', FakeRunner())
    assert isinstance(d, ChimeraApk) and isinstance(d, Apk)
    assert d.trusted_registry and not d.holds_version        # rolling, like Alpine


def test_install_enables_the_user_repo_once_then_installs_non_interactively():
    r = Notes([('apk info -e chimera-repo-user', 1, '')])
    d = ChimeraApk(r)
    assert d.install(_rc('bat')).ok
    assert r.calls == ['apk info -e chimera-repo-user',
                       'sudo apk add --no-interactive chimera-repo-user && apk update',
                       'sudo apk add --no-interactive bat']
    assert r.notes and 'user' in r.notes[0] and 'chimera-repo-user' in r.notes[0]
    r.calls.clear()
    assert d.install(_rc('fish')).ok                        # once per run: no second probe
    assert r.calls == ['sudo apk add --no-interactive fish']


def test_an_enabled_user_repo_is_left_alone_without_a_note():
    r = Notes([('apk info -e chimera-repo-user', 0, 'chimera-repo-user\n')])
    assert ChimeraApk(r).upgrade(_rc('bat')).ok
    assert r.calls == ['apk info -e chimera-repo-user', 'sudo apk add --no-interactive --upgrade bat']
    assert not r.notes


def test_a_failed_repo_setup_stops_the_install_named():
    r = FakeRunner([('apk info -e chimera-repo-user', 1, ''), ('chimera-repo-user && apk update', 1, '')])
    res = ChimeraApk(r).install(_rc('bat'))
    assert not res.ok and 'user' in res.output and 'bat' in res.output
    assert not any(c.endswith('apk add --no-interactive bat') for c in r.calls)


def test_remove_and_upgrade_all_are_non_interactive_and_need_no_repo():
    r = FakeRunner()
    d = ChimeraApk(r)
    assert d.uninstall(_rc('bat')).ok and d.upgrade_all().ok
    assert r.calls == ['sudo apk del --no-interactive bat', 'sudo apk upgrade --no-interactive']


def test_version_reads_are_apks():
    r = FakeRunner([('apk list --installed bat', 0, 'bat-0.26.1-r0 x86_64 {bat} (MIT) [installed]\n'),
                    ('apk list bat', 0, 'bat-0.26.1-r0 x86_64 {bat} (MIT)\n')])
    d = ChimeraApk(r)
    assert d.get_version(_rc('bat')) == '0.26.1-r0'
    assert d.get_latest(_rc('bat')) == '0.26.1-r0'


def test_lock_and_set_version_decline_naming_chimera():
    d = ChimeraApk(FakeRunner())
    for res in (d.lock(_rc('bat')), d.set_version(_rc('bat'), '0.25')):
        assert not res.ok and res.advisory and 'Chimera' in res.output and 'Alpine' not in res.output
    assert 'Alpine' in Apk(FakeRunner()).lock(_rc('bat')).output     # Alpine's wording unchanged


def test_the_repo_package_is_plumbing_not_an_explicit_pick(tmp_path, monkeypatch):
    world = tmp_path / 'world'
    world.write_text('base-bootstrap\nchimera-repo-user\nbat\n')
    monkeypatch.setattr(ChimeraApk, 'WORLD', str(world))
    assert ChimeraApk(FakeRunner()).explicit_keys() == {'base-bootstrap', 'bat'}
    monkeypatch.setattr(ChimeraApk, 'WORLD', str(tmp_path / 'absent'))
    assert ChimeraApk(FakeRunner()).explicit_keys() is None


def test_pretend_shows_the_repo_step_it_cannot_probe():
    class Pretend(Notes):
        pretend = True

        def run(self, cmd, **kw):
            from configsys.runner import Result
            self.calls.append(f'sudo {cmd}' if kw.get('sudo') else cmd)
            return Result(cmd, 0, pretended=True)
    r = Pretend()
    assert ChimeraApk(r).install(_rc('bat')).ok
    assert 'sudo apk add --no-interactive chimera-repo-user && apk update' in r.calls
    assert r.notes and 'if it isn' in r.notes[0]
