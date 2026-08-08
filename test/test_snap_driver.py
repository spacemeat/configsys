'''Snap driver: command shape (sudo, --classic/--channel), version parsing from `snap list` /
`snap info`, and hold/unhold locking. Fake runner returns canned outputs.'''

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver, is_supported
from configsys.drivers.snap import Snap
from configsys.runner import Result, Runner


def dist(comp='vscode', name='code', **fields):
    return ResolvedComponent(key=f'snap\\{comp}', driver='snap', comp=comp,
                             fields={'name': name, **fields})


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


def test_registered_and_privileged_system():
    d = get_driver('snap', Runner(pretend=True))
    assert isinstance(d, Snap) and is_supported('snap')
    assert d.privileged is True and d.default_scope == 'system' and d.honors_scope is False


def test_install_flags_classic_and_channel():
    r = FakeRunner()
    Snap(r).install(dist(name='code', classic='true'))
    Snap(r).install(dist(comp='node', name='node', channel='20/stable'))
    Snap(r).install(dist(comp='btop', name='btop'))            # plain
    assert r.calls[0] == 'sudo snap install --classic code'
    assert r.calls[1] == 'sudo snap install --channel=20/stable node'
    assert r.calls[2] == 'sudo snap install btop'


def test_uninstall_upgrade_and_hold_unhold():
    r = FakeRunner()
    Snap(r).uninstall(dist())
    Snap(r).upgrade(dist())
    Snap(r).lock(dist())
    Snap(r).unlock(dist())
    assert r.calls == ['sudo snap remove code', 'sudo snap refresh code',
                       'sudo snap refresh --hold code', 'sudo snap refresh --unhold code']


def test_get_version_parses_snap_list():
    out = ('Name  Version   Rev    Tracking       Publisher   Notes\n'
           'code  1.96.4    189    latest/stable  vscode✓     classic\n')
    r = FakeRunner([('snap list', 0, out)])
    assert Snap(r).get_version(dist()) == '1.96.4'
    # not installed -> the command fails
    r2 = FakeRunner([('snap list', 1, 'error: no matching snaps installed')])
    assert Snap(r2).get_version(dist()) is None


def test_get_latest_reads_channel_and_lock_note():
    info = ('name:    code\n'
            'summary: Code editing. Redefined.\n'
            'channels:\n'
            '  latest/stable:    1.97.0 2026-01-05 (200) 350MB classic\n'
            '  latest/candidate: 1.97.1 2026-01-06 (201) 350MB classic\n')
    r = FakeRunner([('snap info', 0, info)])
    assert Snap(r).get_latest(dist()) == '1.97.0'
    assert Snap(r).get_latest(dist(channel='candidate')) == '1.97.1'
    # held snap -> is_locked True
    held = ('Name  Version  Rev  Tracking       Publisher  Notes\n'
            'code  1.96.4   189  latest/stable  vscode✓    held\n')
    rl = FakeRunner([('snap list', 0, held)])
    assert Snap(rl).is_locked(dist()) is True
