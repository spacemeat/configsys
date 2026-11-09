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
    drv = StubDrv({'install': Result('apt-get install -y sysdig', 100)}, version=None)
    real_install = drv.install

    def install(rc):                                  # absent before; the package landed anyway
        drv.version = '0.40.0'
        return real_install(rc)
    drv.install = install
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


def test_install_ok_but_undetected_is_flagged(tmp_path, monkeypatch):
    # swig (a stale installed-name), claude-code (binary off PATH), go tools (go only from the
    # tarball): each install ran fine but the component read "not installed" — silently, discovered
    # later. The loop now checks detection right after, and says so.
    lines = []
    monkeypatch.setattr(drivers_mod, 'get_driver', lambda *a, **k: StubDrv(version=None))
    res = actions.run_plan(_ctx(tmp_path), [('install', 'apt\\\\swig', _unit('swig'))],
                           on_line=lines.append)
    (o,) = res.outcomes
    assert o.ok and o.undetected
    assert any('NOT DETECTED' in ln for ln in lines)


def test_detected_install_is_plain_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(drivers_mod, 'get_driver', lambda *a, **k: StubDrv(version='4.2.0'))
    res = actions.run_plan(_ctx(tmp_path), [('install', 'apt\\\\swig', _unit('swig'))],
                           on_line=lambda *_a: None)
    assert res.outcomes[0].ok and not res.outcomes[0].undetected


def test_config_drivers_are_not_post_checked():
    drv = SimpleNamespace(name='dotfiles', get_version=lambda rc: None)
    assert actions.detected_after(drv, _unit('x', 'dotfiles'))


def test_a_driver_exception_fails_that_op_and_the_batch_still_saves(tmp_path, monkeypatch):
    # B10: a driver bug is one failed op — the rest run, sudo is released, the ledger is saved
    from configsys.ledger import Ledger
    released = []
    ctx = _ctx(tmp_path)
    ctx.runner.end_sudo = lambda: released.append(True)
    drv = StubDrv()

    def install(rc):
        if rc.comp == 'a':
            raise ValueError('parse blew up')
        return Result('', 0)
    drv.install = install
    led = Ledger()
    monkeypatch.setattr(drivers_mod, 'get_driver', lambda *a, **k: drv)
    monkeypatch.setattr(actions, 'detected_after', lambda *a: True)
    res = actions.run_plan(ctx, [('install', 'apt\\a', _unit('a')), ('lock', 'apt\\b', _unit('b'))],
                           ledger=led, on_line=lambda *_a: None)
    assert [o.ok for o in res.outcomes] == [False, True]
    assert 'parse blew up' in res.outcomes[0].detail
    assert released == [True]
    assert Ledger.load(ctx.paths).is_locked('apt\\b')


def test_an_escaping_error_still_releases_sudo_and_saves(tmp_path, monkeypatch):
    from configsys.ledger import Ledger
    released = []
    ctx = _ctx(tmp_path)
    ctx.runner.end_sudo = lambda: released.append(True)
    drv = StubDrv()
    led = Ledger()
    monkeypatch.setattr(drivers_mod, 'get_driver', lambda *a, **k: drv)

    def boom(*a, **k):
        raise RuntimeError('reportgen broke')
    from configsys import reportgen
    monkeypatch.setattr(reportgen, 'failure_from_result', boom)
    drv.results = {'lock': Result('x', 1)}        # a failure -> failure_from_result raises
    import pytest as _pt
    with _pt.raises(RuntimeError):
        actions.run_plan(ctx, [('lock', 'apt\\b', _unit('b'))], ledger=led, on_line=lambda *_a: None)
    assert released == [True] and ctx.paths.ledger_file.exists()


def test_a_failed_reinstall_of_an_unchanged_install_is_a_failure(tmp_path, monkeypatch):
    # B17 / actions-06: `install --no-deps folly` rebuilding an installed unit — the build fails, the
    # OLD build is still there: that's a failure, not "installed with a warning" + exit 0
    drv = StubDrv({'install': Result('make', 2)}, version='1.0')
    res = _run(tmp_path, monkeypatch, drv, [('install', 'source\\folly', _unit('folly', 'source'))])
    o = res.outcomes[0]
    assert not o.ok and not o.installed_with_warning and res.n_fatal == 1 and res.rc_code == 2


def test_fix_scope_runs_in_the_loop_and_refreshes_the_receipt(tmp_path, monkeypatch):
    # D3 / actions-15: fix-scope is a run_plan op (guard, failure record) and the receipt moves too
    from configsys.ledger import Ledger
    drv = StubDrv()
    drv.honors_scope = True
    drv.get_installed = lambda rc: ('1.0', 'user')
    drv.scope = lambda rc: rc.fields.get('scope') or 'system'
    calls = []
    drv.reconcile_scope = lambda rc, a, b: (calls.append((a, b)), Result('', 0))[1]
    led = Ledger()
    monkeypatch.setattr(drivers_mod, 'get_driver', lambda *a, **k: drv)
    rc = _unit('tool', 'tarball')
    ctx = _ctx(tmp_path)
    res = actions.run_plan(ctx, [('fix-scope', rc.key, rc)], ledger=led, on_line=lambda *_a: None)
    assert res.outcomes[0].ok and calls == [('user', 'system')]
    assert Ledger.load(ctx.paths).records[rc.key]['receipt']['fields']['scope'] == 'system'


def test_set_version_refuses_a_non_version_before_any_driver_runs(tmp_path, monkeypatch):
    # drivers-lang-28: a script's set-version-cmd / a source build splice $VERSION raw — the requested
    # version is checked once, here, for every driver and both surfaces
    calls = []

    class Recording:
        pretend = False

        def run(self, cmd, **kw):
            calls.append(cmd)
            return Result(cmd, 0)

        def end_sudo(self):
            pass
    ctx = _ctx(tmp_path)
    ctx.runner = Recording()
    rc = ResolvedComponent(key='script\\tool', driver='script', comp='tool',
                           fields={'name': 'tool', 'set-version-cmd': 'install-tool $VERSION'})
    for bad in ('1.2 3', '$(id)', '-rf'):
        res = actions.run_plan(ctx, [('set-version', 'script\\tool', rc)], version=bad,
                               on_line=lambda *_a: None)
        assert not res.outcomes[0].ok and res.n_fatal == 1
        assert repr(bad) in res.outcomes[0].detail and 'not a version' in res.outcomes[0].detail
    assert calls == []
    res = actions.run_plan(ctx, [('set-version', 'script\\tool', rc)], version='1.2.3',
                           on_line=lambda *_a: None)
    assert res.outcomes[0].ok and calls == ['PATH="$HOME/.local/bin:$PATH"; install-tool 1.2.3']
