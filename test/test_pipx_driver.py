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


def test_upgrade_with_interpreter_pin_reinstalls_with_that_python():
    # `pipx upgrade` reuses the venv's python and `pipx install --force` IGNORES --python; only
    # `pipx reinstall` rebuilds the venv with a new interpreter (and re-resolves to latest). A venv
    # built on py3.10 otherwise caps mitmproxy at 11.x.
    r = Runner(pretend=True)
    Pipx(r).upgrade(dist(name='mitmproxy', python='/usr/bin/python3.13'))
    assert r.calls == ['uv --version',
                       'python3 -m pipx reinstall --python /usr/bin/python3.13 mitmproxy']


def test_upgrade_without_pin_stays_a_plain_upgrade():
    r = Runner(pretend=True)
    Pipx(r).upgrade(dist(name='black'))
    assert r.calls == ['python3 -m pipx upgrade black']    # no interpreter probe, no --force


def test_get_version_matches_pep503_normalized_name():
    # route `name: Faker`, but pipx stores the venv under the PEP 503 name `faker` -> presence must
    # still match (else configsys thinks it's uninstalled and re-stages an install every time).
    r = FakeRunner(responses=[('pipx list --json', 0, _pipx_list(name='faker', version='40.37.0'))])
    assert Pipx(r).get_version(dist(comp='faker', name='Faker')) == '40.37.0'


def test_get_latest_falls_back_to_pypi_for_a_bare_pipx_binding(monkeypatch):
    # no `version:` spec on the route -> get_latest still reports a latest by querying PyPI for the
    # dist name (the pipx `name` IS a PyPI distribution).
    import configsys.versions as vmod
    seen = {}

    def fake_discover(spec, paths=None, **kw):
        seen['spec'] = spec
        return '40.37.0'

    monkeypatch.setattr(vmod, 'discover', fake_discover)
    assert Pipx(FakeRunner()).get_latest(dist(comp='faker', name='Faker')) == '40.37.0'
    assert seen['spec'] == {'pypi': 'Faker'}


def test_get_latest_prefers_an_explicit_version_spec(monkeypatch):
    # an explicit `version: { pypi: ... }` still wins over the bare-name fallback.
    import configsys.versions as vmod
    monkeypatch.setattr(vmod, 'discover', lambda spec, paths=None, **kw: '9.9.9')
    got = Pipx(FakeRunner()).get_latest(dist(name='Faker', version_spec={'pypi': 'Faker'}))
    assert got == '9.9.9'


def test_get_latest_scopes_to_the_venv_python(monkeypatch):
    # an installed venv on py3.10 -> get_latest queries PyPI SCOPED to that interpreter, so a newer
    # release that dropped py3.10 isn't falsely reported as an available upgrade (the pywal16 bug).
    import configsys.versions as vmod
    seen = {}

    def fake_discover(spec, paths=None, **kw):
        seen['spec'] = spec
        return '3.8.10'

    monkeypatch.setattr(vmod, 'discover', fake_discover)
    listing = json.dumps({'venvs': {'pywal16': {'metadata': {
        'main_package': {'package': 'pywal16', 'package_version': '3.8.10'},
        'python_version': 'Python 3.10.12'}}}})
    r = FakeRunner(responses=[('pipx list --json', 0, listing)])
    assert Pipx(r).get_latest(dist(comp='pywal16', name='pywal16')) == '3.8.10'
    assert seen['spec'] == {'pypi': 'pywal16', 'python': '3.10.12'}


def test_get_latest_uses_python_pin_when_not_installed(monkeypatch):
    # not installed, but a `python:` pin means the fresh venv will use it -> scope to the pin.
    import configsys.versions as vmod
    seen = {}
    monkeypatch.setattr(vmod, 'discover',
                        lambda spec, paths=None, **kw: seen.setdefault('spec', spec) and None or '1.0')
    r = FakeRunner(responses=[('pipx list --json', 0, json.dumps({'venvs': {}}))])
    Pipx(r).get_latest(dist(comp='qtile', name='qtile', python='python3.12'))
    assert seen['spec'] == {'pypi': 'qtile', 'python': '3.12'}


def test_get_latest_pin_overrides_an_older_installed_venv(monkeypatch):
    # venv is on py3.10 but the route PINS py3.13 -> scope to the pin (intent), so a newer release the
    # pin can reach reads as an available upgrade (the `pipx reinstall --python` path then applies it).
    import configsys.versions as vmod
    seen = {}

    def fake_discover(spec, paths=None, **kw):
        seen['spec'] = spec
        return '3.8.15'

    monkeypatch.setattr(vmod, 'discover', fake_discover)
    listing = json.dumps({'venvs': {'pywal16': {'metadata': {
        'main_package': {'package_version': '3.8.10'}, 'python_version': 'Python 3.10.12'}}}})
    r = FakeRunner(responses=[('pipx list --json', 0, listing)])
    got = Pipx(r).get_latest(dist(comp='pywal16', name='pywal16', python='/usr/bin/python3.13'))
    assert got == '3.8.15' and seen['spec'] == {'pypi': 'pywal16', 'python': '3.13'}
