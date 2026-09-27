'''actions.run_plan — the ONE op-execution loop the CLI and TUI share (D3). Verifies the behaviors
the TUI historically lacked (its own loop had none of these): the set-version op, the advisory
"needs your input" outcome, verify-after-fail (installed-with-a-warning), and EVERY failure recorded
(not just the last).'''

from types import SimpleNamespace

import configsys.drivers as drivers_mod
from configsys import actions
from configsys.componentObj import ResolvedComponent
from configsys.paths import Paths
from configsys.runner import Result


class StubDrv:
    honors_scope = False

    def __init__(self, results=None, version=None, latest=None):
        self.results = results or {}
        self.version = version
        self.latest = latest
        self.set_to = None

    def _r(self, op):
        return self.results.get(op, Result('', 0))
    def install(self, rc):
        return self._r('install')
    def uninstall(self, rc):
        return self._r('remove')
    def upgrade(self, rc):
        return self._r('upgrade')
    def set_version(self, rc, v):
        self.set_to = v
        return self._r('set-version')
    def lock(self, rc):
        return self._r('lock')
    def unlock(self, rc):
        return self._r('unlock')
    def get_version(self, rc):
        return self.version
    def get_latest(self, rc):
        return self.latest


def _unit(name, driver='apt'):
    return ResolvedComponent(key=f'{driver}\\{name}', driver=driver, comp=name, fields={'name': name})


def _ctx(tmp_path):
    return SimpleNamespace(runner=SimpleNamespace(pretend=False, end_sudo=lambda: None),
                           paths=Paths(env={'HOME': str(tmp_path),
                                            'CONFIGSYS_STATE_DIR': str(tmp_path / 's')}))


def _run(tmp_path, monkeypatch, drv, plan, **kw):
    monkeypatch.setattr(drivers_mod, 'get_driver', lambda *a, **k: drv)
    return actions.run_plan(_ctx(tmp_path), plan, on_line=lambda *_a: None, **kw)


def test_set_version_is_dispatched_with_the_version(tmp_path, monkeypatch):
    drv = StubDrv()
    res = _run(tmp_path, monkeypatch, drv, [('set-version', 'apt\\btop', _unit('btop'))], version='1.2.3')
    assert drv.set_to == '1.2.3'                      # the TUI's old loop returned "no result" here
    assert res.outcomes[0].ok and res.n_fatal == 0


def test_advisory_result_is_needs_input_not_a_failure(tmp_path, monkeypatch):
    drv = StubDrv({'install': Result('', 1, stderr='git config already present — capture to adopt',
                                      advisory=True)})
    res = _run(tmp_path, monkeypatch, drv, [('install', 'dotfiles\\git', _unit('git', 'dotfiles'))])
    assert res.outcomes[0].advisory and not res.outcomes[0].ok
    assert res.n_fatal == 0 and res.failures == []   # explained, not reported


def test_verify_after_fail_downgrades_to_installed_with_warning(tmp_path, monkeypatch):
    # apt exits non-zero on a failed Recommends though the package installed — present now -> a warning
    drv = StubDrv({'install': Result('apt-get install -y sysdig', 100)}, version='0.40.0')
    res = _run(tmp_path, monkeypatch, drv, [('install', 'apt\\sysdig', _unit('sysdig'))])
    o = res.outcomes[0]
    assert o.ok and o.installed_with_warning and res.n_fatal == 0
    assert res.failures and res.failures[0].get('installed') == 'true'   # recorded for `report`


def test_every_failure_is_recorded_not_just_the_last(tmp_path, monkeypatch):
    drv = StubDrv({'install': Result('boom', 1)}, version=None)   # both fail, nothing present after
    plan = [('install', 'apt\\a', _unit('a')), ('install', 'apt\\b', _unit('b'))]
    res = _run(tmp_path, monkeypatch, drv, plan)
    assert res.n_fatal == 2 and len(res.failures) == 2 and res.rc_code == 1



import pytest  # noqa: E402


@pytest.mark.parametrize('driver, expect', [
    ('cargo', False), ('pipx', False), ('tarball', False),       # user-scope, no internal sudo
    ('apt', True), ('flatpak', False), ('snap', True),            # privileged drivers
    ('script', True), ('source', True), ('aur', True),            # sudo INSIDE their commands
])
def test_may_need_root(driver, expect):
    from configsys.drivers import get_driver
    from configsys.runner import Runner
    drv = get_driver(driver, Runner(pretend=True), None)
    assert actions._may_need_root(drv, _unit('x', driver)) is expect


def test_may_need_root_assumes_yes_for_plugin_drivers():
    # a code plugin's driver (blender/kicad builds sudo internally) — unknown, so authenticate up front
    assert actions._may_need_root(StubDrv(), _unit('x', 'blender-build')) is True


def test_run_plan_authenticates_once_up_front(tmp_path, monkeypatch):
    began = []
    ctx = _ctx(tmp_path)
    ctx.runner.begin_sudo = lambda on_line=None: began.append('begin')
    order = []
    drv = StubDrv()
    drv.install = lambda rc: (order.append(('install', began[:])), Result('', 0))[1]
    monkeypatch.setattr(drivers_mod, 'get_driver', lambda *a, **k: drv)
    actions.run_plan(ctx, [('install', 'apt\\a', _unit('a')), ('install', 'apt\\b', _unit('b'))],
                     on_line=lambda *_a: None)
    assert began == ['begin']                                     # once, for the whole batch
    assert order[0] == ('install', ['begin'])                     # BEFORE the first op runs
