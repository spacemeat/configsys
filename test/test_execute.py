import contextlib
from types import SimpleNamespace

from configsys.componentObj import ResolvedComponent
from configsys.ledger import Ledger
from configsys.paths import Paths
from configsys.runner import Result
from configsys.tui.menu import _summary_note, execute_plan


class FakeRunner:
    '''Fails any command containing one of `fail_substrings`.'''

    def __init__(self, fail_substrings=()):
        self.fail = tuple(fail_substrings)
        self.calls = []
        self.pretend = False
        self.tui_active = False

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None, cwd=None, env=None):
        full = f'sudo {cmd}' if sudo else cmd
        self.calls.append(full)
        code = 100 if any(s in cmd for s in self.fail) else 0
        return Result(full, code)

    def end_sudo(self):
        pass                       # batch sudo-session release; a no-op for the stub

    @contextlib.contextmanager
    def sudo_session(self):
        yield                      # (Runner.sudo_session's release is end_sudo, above)


def unit(name, driver='apt'):
    return ResolvedComponent(key=f'{driver}\\{name}', driver=driver, comp=name,
                             fields={'name': name})


def ctx_for(tmp_path, runner):
    return SimpleNamespace(
        runner=runner,
        paths=Paths(env={'HOME': str(tmp_path), 'CONFIGSYS_STATE_DIR': str(tmp_path / 's')}),
    )


def test_failed_install_recorded_others_succeed(tmp_path, capsys):
    fr = FakeRunner(fail_substrings=['apt-get install -y btop'])
    ctx = ctx_for(tmp_path, fr)
    plan = [
        ('install', 'apt\\btop', unit('btop')),
        ('install', 'apt\\fzf', unit('fzf')),
    ]
    outcomes = execute_plan(ctx, plan, Ledger())
    assert [o.ok for o in outcomes] == [False, True]
    assert outcomes[0].detail == 'exit 100'
    assert _summary_note(outcomes) == '1 ok, 1 failed'


def test_failed_lock_not_persisted_to_ledger(tmp_path):
    fr = FakeRunner(fail_substrings=['apt-mark hold ripgrep'])
    ctx = ctx_for(tmp_path, fr)
    led = Ledger()
    plan = [
        ('lock', 'apt\\btop', unit('btop')),        # succeeds
        ('lock', 'apt\\ripgrep', unit('ripgrep')),  # fails
    ]
    outcomes = execute_plan(ctx, plan, led)
    assert led.is_locked('apt\\btop') is True
    assert led.is_locked('apt\\ripgrep') is False
    assert [o.ok for o in outcomes] == [True, False]


def test_unsupported_family_is_a_failed_outcome(tmp_path, capsys):
    ctx = ctx_for(tmp_path, FakeRunner())
    plan = [('install', 'nosuchvia\\foo', unit('foo', driver='nosuchvia'))]
    outcomes = execute_plan(ctx, plan, Ledger())
    assert outcomes[0].ok is False
    assert 'unsupported driver' in outcomes[0].detail


def test_dispatch_op_prints_the_failure_reason_to_the_console(tmp_path, capsys, monkeypatch):
    # a driver that bails pre-flight (Result.fail -> reason in output, no command) must have its
    # reason SHOWN on the console, not buried only in last-failure.hu.
    from configsys import app
    from configsys.app import Context, build_parser

    class StubDrv:
        honors_scope = False

        def install(self, rc):
            return Result.fail('blender-build: optix-root ~/sdks/optix has no include/optix.h')

    # modules that bind `get_driver` at import must import BEFORE the patch, or they keep the stub
    # for every later test in the session
    import importlib
    for mod in ('versionreport', 'orphans', 'stranded', 'detection', 'sysupdates', 'installState'):
        importlib.import_module(f'configsys.{mod}')
    import configsys.drivers as drivers_mod           # run_plan (in actions) resolves get_driver here
    monkeypatch.setattr(drivers_mod, 'get_driver', lambda *a, **k: StubDrv())
    monkeypatch.setattr(app, 'get_driver', lambda *a, **k: StubDrv())   # prepare_units' scope check
    # --pretend: the op loop's native index refresh and up-front sudo must never run for real here
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', '--pretend',
                                             'inspect']))
    code = app._dispatch_op(ctx, ['git'], 'install')
    out = capsys.readouterr().out
    assert code == 1 and 'FAILED (exit 1)' in out
    assert 'optix-root ~/sdks/optix has no include/optix.h' in out   # the WHY is on the console


def test_summary_note_formatting():
    class O:
        def __init__(self, ok):
            self.ok = ok

    assert _summary_note([O(True), O(True)]) == '2 ok'
    assert _summary_note([O(True), O(False)]) == '1 ok, 1 failed'
    assert _summary_note([O(False)]) == '0 ok, 1 failed'


# -- review-2026-11-2 B2: a version lock is honored by every op path --------------------------------

def _run(tmp_path, plan, led, version=None):
    from configsys.actions import run_plan
    fr = FakeRunner()
    lines = []
    res = run_plan(ctx_for(tmp_path, fr), plan, ledger=led, version=version, on_line=lines.append)
    return fr, res, lines


def test_an_explicit_upgrade_of_a_locked_unit_is_refused(tmp_path):
    led = Ledger()
    led.set_lock('apt\\btop', True)
    fr, res, lines = _run(tmp_path, [('upgrade', 'apt\\btop', unit('btop'))], led)
    assert not any('install' in c for c in fr.calls)             # the driver was never asked
    assert res.outcomes[0].detail == 'locked' and res.rc_code == 1
    assert any('configsys unlock btop' in ln for ln in lines)
    assert led.is_locked('apt\\btop')


def test_remove_ends_the_lock_and_set_version_re_holds(tmp_path):
    led = Ledger()
    led.set_lock('apt\\btop', True)
    fr, res, _ = _run(tmp_path, [('remove', 'apt\\btop', unit('btop'))], led)
    assert res.outcomes[0].ok and not led.is_locked('apt\\btop')
    assert fr.calls.index(next(c for c in fr.calls if 'unhold' in c)) < \
        fr.calls.index(next(c for c in fr.calls if 'remove' in c))   # released before removing
    led.set_lock('apt\\fzf', True)
    fr, res, _ = _run(tmp_path, [('set-version', 'apt\\fzf', unit('fzf'))], led, version='1.0')
    seq = [c for c in fr.calls if 'mark' in c or 'install' in c]
    assert 'unhold' in seq[0] and 'hold' in seq[-1] and 'unhold' not in seq[-1]
    assert led.is_locked('apt\\fzf')


def test_a_lock_follows_the_component_across_a_method_swap(tmp_path):
    led = Ledger()
    led.set_lock('apt\\btop', True)
    plan = [('remove', 'apt\\btop', unit('btop')), ('install', 'snap\\btop', unit('btop', driver='snap'))]
    fr, res, _ = _run(tmp_path, plan, led)
    assert all(o.ok for o in res.outcomes)
    assert not led.is_locked('apt\\btop') and led.is_locked('snap\\btop')
