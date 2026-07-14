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


def unit(name, family='apt'):
    return ResolvedComponent(key=f'{family}\\{name}', family=family, comp=name,
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
    plan = [('install', 'dotfiles\\neovim', unit('neovim', family='dotfiles'))]
    outcomes = execute_plan(ctx, plan, Ledger())
    assert outcomes[0].ok is False
    assert 'unsupported family' in outcomes[0].detail


def test_summary_note_formatting():
    class O:
        def __init__(self, ok):
            self.ok = ok

    assert _summary_note([O(True), O(True)]) == '2 ok'
    assert _summary_note([O(True), O(False)]) == '1 ok, 1 failed'
    assert _summary_note([O(False)]) == '0 ok, 1 failed'
