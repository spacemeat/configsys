import json

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.pipx import Pipx
from configsys.runner import Result, Runner


def dist(comp='apod', name='termapod', version_spec=None, python=None):
    fields = {'name': name}
    if version_spec is not None:
        fields['version'] = version_spec
    if python is not None:
        fields['python'] = python
    return ResolvedComponent(key=f'pipx\\{comp}', driver='pipx', comp=comp, fields=fields)


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

    def echo(self, msg):
        pass                       # the driver's backend note; a no-op for the stub


def _pipx_list(name='termapod', version='0.1.3'):
    return json.dumps({'venvs': {name: {'metadata': {
        'main_package': {'package': name, 'package_version': version}}}}})


def test_registered_and_unprivileged():
    fam = get_driver('pipx', Runner(pretend=True))
    assert isinstance(fam, Pipx) and is_supported('pipx')
    assert fam.privileged is False


def test_install_uninstall_upgrade_commands_are_user_space():
    # install probes uv up front to choose pipx's backend; pretend uv-probe returns nothing (no uv)
    # so the default backend is used (no --backend flag). uninstall/upgrade don't probe.
    r = Runner(pretend=True)
    Pipx(r).install(dist())
    Pipx(r).uninstall(dist())
    Pipx(r).upgrade(dist())
    assert r.calls == [
        'uv --version',
        'python3 -m pipx install termapod',
        'python3 -m pipx uninstall termapod',
        'python3 -m pipx upgrade termapod',
    ]
    assert all('sudo' not in c for c in r.calls)   # user-space, no root


def test_install_uses_pip_backend_when_resident_uv_too_old():
    # UP-FRONT probe: a uv older than pipx needs -> pipx builds the venv with its pip backend instead
    # (chosen deliberately + noted, not after a failed attempt). Same pipx method, same venv.
    r = FakeRunner(responses=[('uv --version', 0, 'uv 0.8.3')])
    res = Pipx(r).install(dist())
    assert res.ok
    assert r.calls == ['uv --version', 'python3 -m pipx install --backend pip termapod']


def test_install_keeps_default_backend_when_uv_new_enough():
    r = FakeRunner(responses=[('uv --version', 0, 'uv 0.9.20')])   # >= _UV_MIN
    Pipx(r).install(dist())
    assert r.calls == ['uv --version', 'python3 -m pipx install termapod']   # no --backend flag


def test_install_keeps_default_backend_when_uv_absent():
    r = FakeRunner(responses=[('uv --version', 1, '')])            # uv not on PATH -> probe fails
    Pipx(r).install(dist())
    assert r.calls == ['uv --version', 'python3 -m pipx install termapod']


def test_backend_probe_is_cached_across_ops():
    # one driver instance probes uv ONCE (a batch shouldn't re-probe / re-note per component).
    r = FakeRunner(responses=[('uv --version', 0, 'uv 0.8.3')])
    p = Pipx(r)
    p.install(dist(comp='a', name='a'))
    p.install(dist(comp='b', name='b'))
    assert r.calls.count('uv --version') == 1
    assert r.calls[1:] == ['python3 -m pipx install --backend pip a',
                           'python3 -m pipx install --backend pip b']


def test_set_version_forces_reinstall():
    r = Runner(pretend=True)
    Pipx(r).set_version(dist(), '0.1.2')
    assert r.calls == ['uv --version', 'python3 -m pipx install --force termapod==0.1.2']


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


def test_interpreter_pin_passes_python_flag_to_pipx():
    r = Runner(pretend=True)
    Pipx(r).install(dist(name='black', python='python3.12'))
    assert r.calls == ['uv --version', 'python3 -m pipx install --python python3.12 black']
