from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.pip import Pip
from configsys.runner import Result, Runner


# The pip driver is now used mainly to bootstrap pipx on OSs without an apt pipx.
def dist(comp='pipx', name='pipx', version_spec=None, python=None):
    fields = {'name': name}
    if version_spec is not None:
        fields['version'] = version_spec
    if python is not None:
        fields['python'] = python
    return ResolvedComponent(key=f'pip\\{comp}', driver='pip', comp=comp, fields=fields)


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


def test_registered_and_unprivileged():
    fam = get_driver('pip', Runner(pretend=True))
    assert isinstance(fam, Pip) and is_supported('pip')
    assert fam.privileged is False


def test_install_uninstall_upgrade_commands_are_user_space():
    r = Runner(pretend=True)
    Pip(r).install(dist())
    Pip(r).uninstall(dist())
    Pip(r).upgrade(dist())
    assert r.calls == [
        'python3 -m pip install --user pipx',
        'python3 -m pip uninstall -y pipx',
        'python3 -m pip install --user --upgrade pipx',
    ]
    assert all('sudo' not in c for c in r.calls)   # user-space, no root


def test_set_version_pins():
    r = Runner(pretend=True)
    Pip(r).set_version(dist(), '1.4.2')
    assert r.calls == ['python3 -m pip install --user pipx==1.4.2']


def test_get_version_from_pip_list():
    # get_version now reads the batched `pip list --format=json` index (PEP-503-normalized), so N
    # units cost one call; the lookup matches case/-_. spelling.
    listing = '[{"name": "Pipx", "version": "1.4.2"}, {"name": "other", "version": "9"}]'
    fr = FakeRunner([('pip list --format=json', 0, listing)])
    assert Pip(fr).get_version(dist()) == '1.4.2'


def test_get_version_not_installed():
    fr = FakeRunner([('pip list --format=json', 0, '[]')])   # not in the listing
    assert Pip(fr).get_version(dist()) is None


def test_get_latest_none_without_spec_and_no_native_lock():
    fam = Pip(Runner(pretend=True))
    assert fam.get_latest(dist(version_spec=None)) is None   # no version spec
    assert fam.is_locked(dist()) is False


def test_get_latest_from_pypi_spec(tmp_path):
    from configsys.paths import Paths
    from configsys.versions import VersionCache
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path),
                       'CONFIGSYS_STATE_DIR': str(tmp_path / 's')})
    VersionCache({'pypi:pipx': {'version': '1.5.0', 'url': None,
                                'fetched': 1e12}}).save(paths)
    rc = dist(version_spec={'pypi': 'pipx'})
    assert Pip(Runner(pretend=True), paths=paths).get_latest(rc) == '1.5.0'


def test_location_is_local_bin():
    assert Pip(Runner(pretend=True)).location(dist()) == '~/.local/bin'


def test_interpreter_pin_installs_into_a_specific_python():
    r = Runner(pretend=True)
    Pip(r).install(dist(name='black', python='python3.12'))
    assert r.calls == ['python3.12 -m pip install --user black']   # not bare `python3`


def test_interpreter_pin_get_version_probes_that_python():
    show = 'Name: black\nVersion: 24.1.0\n'
    fr = FakeRunner([('python3.12 -m pip show black', 0, show)])   # NOT the default-python batch
    assert Pip(fr).get_version(dist(name='black', python='python3.12')) == '24.1.0'
