import json

from configsys.componentObj import ResolvedComponent
from configsys.families import get_family, is_supported
from configsys.families.pipx import Pipx
from configsys.runner import Result, Runner


def dist(comp='apod', name='termapod', version_spec=None):
    fields = {'name': name}
    if version_spec is not None:
        fields['version'] = version_spec
    return ResolvedComponent(key=f'pipx\\{comp}', family='pipx', comp=comp, fields=fields)


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


def _pipx_list(name='termapod', version='0.1.3'):
    return json.dumps({'venvs': {name: {'metadata': {
        'main_package': {'package': name, 'package_version': version}}}}})


def test_registered_and_unprivileged():
    fam = get_family('pipx', Runner(pretend=True))
    assert isinstance(fam, Pipx) and is_supported('pipx')
    assert fam.privileged is False


def test_install_uninstall_upgrade_commands_are_user_space():
    r = Runner(pretend=True)
    Pipx(r).install(dist())
    Pipx(r).uninstall(dist())
    Pipx(r).upgrade(dist())
    assert r.calls == [
        'python3 -m pipx install termapod',
        'python3 -m pipx uninstall termapod',
        'python3 -m pipx upgrade termapod',
    ]
    assert all('sudo' not in c for c in r.calls)   # user-space, no root


def test_set_version_forces_reinstall():
    r = Runner(pretend=True)
    Pipx(r).set_version(dist(), '0.1.2')
    assert r.calls == ['python3 -m pipx install --force termapod==0.1.2']


def test_get_version_parses_pipx_list_json():
    fr = FakeRunner([('pipx list --json', 0, _pipx_list('termapod', '0.1.3'))])
    assert Pipx(fr).get_version(dist()) == '0.1.3'


def test_get_version_not_installed():
    fr = FakeRunner([('pipx list --json', 0, _pipx_list('somethingelse', '9.9'))])
    assert Pipx(fr).get_version(dist()) is None


def test_get_version_handles_bad_json():
    fr = FakeRunner([('pipx list --json', 0, 'not json')])
    assert Pipx(fr).get_version(dist()) is None


def test_get_latest_none_without_spec_and_no_native_lock():
    fam = Pipx(Runner(pretend=True))
    assert fam.get_latest(dist()) is None
    assert fam.is_locked(dist()) is False


def test_location_is_local_bin():
    assert Pipx(Runner(pretend=True)).location(dist()) == '~/.local/bin'
