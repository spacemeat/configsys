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

    monkeypatch.setattr(app, 'get_driver', lambda *a, **k: StubDrv())
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))
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
