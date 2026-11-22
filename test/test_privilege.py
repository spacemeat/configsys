'''privilege.py — how configsys gets root: the Sudo / Doas / AlreadyRoot / NoEscalator escalators,
`detect()`'s order, and the runner's batch session driven through each (docs/principles.md).'''

import types

import pytest

from configsys import privilege, runner as R
from configsys.privilege import (DENIED, EACH_STEP, WARM, AlreadyRoot, Doas, NoEscalator, Sudo,
                                 as_root, detect)


def _fake_tool(d, name, *, auth=0, probe=0):
    '''A fake `name` in `d` that logs its argv to `d/<name>.log`, exits `probe` for a `-n` probe and
    `auth` otherwise.'''
    log = d / f'{name}.log'
    script = d / name
    script.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> {log}\n'
                      f'case "$1" in -n) exit {probe};; esac\nexit {auth}\n')
    script.chmod(0o755)
    return log


def _only_on_path(monkeypatch, d):
    monkeypatch.setenv('PATH', str(d))


# -- the escalators ---------------------------------------------------------------------------------

def test_sudo_wraps_and_reads_exactly_as_before():
    s = Sudo()
    assert s.argv_for('apt-get install -y x') == ['sudo', 'bash', '-c', 'apt-get install -y x']
    assert s.prefix == 'sudo ' and s.word == 'sudo' and s.name == 'sudo' and s.needs_auth


def test_doas_wraps_one_root_shell_and_reads_as_doas():
    d = Doas()
    assert d.argv_for('apk add x && rc-update add y') == ['doas', 'bash', '-c',
                                                          'apk add x && rc-update add y']
    assert d.prefix == 'doas ' and d.word == 'doas' and d.name == 'doas' and d.needs_auth


def test_already_root_neither_wraps_nor_asks():
    r = AlreadyRoot()
    assert r.argv_for('apk add x') == ['bash', '-c', 'apk add x']
    assert r.prefix == '' and r.word == '' and not r.needs_auth and r.keepalive() is None
    assert r.may_prompt is None and r.missing is None


def test_no_escalator_names_what_is_missing():
    n = NoEscalator()
    assert 'configsys needs sudo or doas to run this as root' in n.missing
    assert not n.needs_auth and not n.available()
    assert Sudo().missing is None and Doas().missing is None


def test_detect_prefers_root_then_sudo_then_doas(tmp_path, monkeypatch):
    _fake_tool(tmp_path, 'sudo')
    _fake_tool(tmp_path, 'doas')
    _only_on_path(monkeypatch, tmp_path)
    monkeypatch.setattr(privilege.os, 'geteuid', lambda: 1000)
    assert type(detect()) is Sudo                       # both present: sudo
    (tmp_path / 'sudo').unlink()
    assert type(detect()) is Doas                       # a doas-only box (Chimera)
    (tmp_path / 'doas').unlink()
    assert type(detect()) is NoEscalator                # neither
    monkeypatch.setattr(privilege.os, 'geteuid', lambda: 0)
    assert type(detect()) is AlreadyRoot                # euid 0 wins whatever is on PATH


def test_doas_preauth_authenticates_then_probes(tmp_path, monkeypatch):
    log = _fake_tool(tmp_path, 'doas', auth=0, probe=0)       # a `persist` rule: the probe passes
    _only_on_path(monkeypatch, tmp_path)
    assert Doas().preauth() == WARM
    assert log.read_text().splitlines() == ['true', '-n true']


def test_doas_without_persist_reads_each_step(tmp_path, monkeypatch):
    log = _fake_tool(tmp_path, 'doas', auth=0, probe=1)       # authenticated, but nothing remembered
    _only_on_path(monkeypatch, tmp_path)
    d = Doas()
    assert d.preauth() == EACH_STEP
    assert log.read_text().splitlines() == ['true', '-n true']
    note = d.each_step_note
    assert 'each privileged step' in note and 'permit persist :wheel' in note
    assert 'never edits' in note                              # configsys says it; you edit doas.conf


def test_doas_refused_is_denied_without_a_probe(tmp_path, monkeypatch):
    log = _fake_tool(tmp_path, 'doas', auth=1, probe=1)       # wrong password / not permitted
    _only_on_path(monkeypatch, tmp_path)
    assert Doas().preauth() == DENIED
    assert log.read_text().splitlines() == ['true']


def test_doas_has_no_keepalive_but_sudo_refreshes():
    assert Doas().keepalive() is None                         # doas has no refresh: persist is fixed
    k = Sudo().keepalive()                                    # stopped before its first 50s tick
    assert k is not None
    k.stop()


def test_keepalive_refreshes_until_stopped():
    import threading
    ticks = threading.Semaphore(0)
    k = privilege.Keepalive(ticks.release, 0.01)
    assert ticks.acquire(timeout=5) and ticks.acquire(timeout=5)   # it ticks, repeatedly
    k.stop()


def test_may_prompt_names_the_tool():
    assert Sudo().may_prompt == 'sudo may prompt' and Doas().may_prompt == 'doas may prompt'
    assert NoEscalator().may_prompt is None


def test_as_root_reads_the_runners_escalator():
    assert as_root(R.Runner(pretend=True, escalator=Doas())) == 'doas'
    assert as_root(R.Runner(pretend=True, escalator=AlreadyRoot())) == ''
    assert as_root(types.SimpleNamespace(pretend=True)) == 'sudo'   # a stand-in runner: sudo, as recorded


def test_the_test_suite_blocks_a_real_doas():
    import shutil
    fake = shutil.which('doas')
    assert fake and 'fakesudo' in fake                        # conftest's fake comes first on PATH


# -- the runner, through each escalator --------------------------------------------------------------

class _Stub(Doas):
    '''A Doas whose prompt/probe are scripted: preauth -> `got`, authorized -> `probe`.'''
    def __init__(self, order, got=WARM, probe=False):
        self.order, self.got, self.probe = order, got, probe

    def preauth(self):
        self.order.append('preauth')
        return self.got

    def authorized(self):
        return self.probe


def test_pretend_reads_each_escalators_form():
    for esc, want in ((Sudo(), 'sudo apk add x'), (Doas(), 'doas apk add x'),
                      (AlreadyRoot(), 'apk add x'), (NoEscalator(), 'sudo apk add x')):
        r = R.Runner(pretend=True, escalator=esc)
        assert r.run('apk add x', sudo=True).pretended and r.calls == [want]


@pytest.mark.real_runner
def test_doas_privileged_op_runs_under_doas(monkeypatch):
    seen = []
    monkeypatch.setattr(R, '_can_tee', lambda: False)
    monkeypatch.setattr(R.subprocess, 'run',
                        lambda argv, **k: (seen.append(argv),
                                           types.SimpleNamespace(returncode=0, stdout='', stderr=''))[1])
    res = R.Runner(escalator=Doas()).run('apk add x', sudo=True)
    assert res.ok and res.cmd == 'doas apk add x' and seen == [['doas', 'bash', '-c', 'apk add x']]


@pytest.mark.real_runner
def test_already_root_runs_the_shell_directly_and_never_asks(monkeypatch):
    seen, order = [], []
    monkeypatch.setattr(R, '_can_tee', lambda: True)
    monkeypatch.setattr(R, '_run_teed', lambda argv, *a: (seen.append(argv), (0, 'out'))[1])
    monkeypatch.setattr(R, '_run_captured_tty', lambda *a: order.append('cap'))   # no credential to keep
    r = R.Runner(escalator=AlreadyRoot())
    assert r.begin_sudo(order.append) is False and order == []                     # no prompt, no note
    res = r.run('apk add x', sudo=True, capture=False)
    assert res.ok and res.cmd == 'apk add x' and seen == [['bash', '-c', 'apk add x']]


@pytest.mark.real_runner
def test_no_escalator_fails_a_privileged_op_without_running_it(monkeypatch):
    monkeypatch.setattr(R.subprocess, 'run', lambda *a, **k: pytest.fail('ran a privileged op'))
    r = R.Runner(escalator=NoEscalator())
    res = r.run('apk add x', sudo=True)
    assert not res.ok and 'configsys needs sudo or doas to run this as root' in res.output
    said = []
    assert r.begin_sudo(said.append) is False
    assert said and 'neither sudo nor doas' in said[0]


def test_begin_names_doas_when_it_will_prompt():
    order, said = [], []
    r = R.Runner(escalator=_Stub(order, got=WARM, probe=False))
    assert r.begin_sudo(said.append) is True and order == ['preauth']
    assert said and 'authenticating doas' in said[0]
    assert r._keepalive is None                               # nothing to refresh under doas
    r.end_sudo()
    assert r._sudo_warm is False


def test_doas_without_persist_says_so_once_and_never_double_prompts(monkeypatch):
    order, said = [], []
    r = R.Runner(escalator=_Stub(order, got=EACH_STEP))
    assert r.begin_sudo(said.append) is False
    assert any('each privileged step' in s for s in said)
    n = len(said)
    assert r._ensure_sudo() is False and r._ensure_sudo() is False
    assert order == ['preauth'] and len(said) == n            # each op's own prompt is the only one
    r.end_sudo()                                              # a new batch tries again
    assert r._ensure_sudo() is False and order == ['preauth', 'preauth']


def test_a_denied_preauth_is_retried_on_the_next_op():
    order = []
    r = R.Runner(escalator=_Stub(order, got=DENIED))
    assert r._ensure_sudo() is False and r._ensure_sudo() is False
    assert order == ['preauth', 'preauth']                    # (as with sudo before: a cancel isn't final)


@pytest.mark.real_runner
def test_doas_each_step_runs_plain_so_doas_can_prompt(monkeypatch):
    order = []
    monkeypatch.setattr(R, '_can_tee', lambda: True)
    monkeypatch.setattr(R, '_run_captured_tty', lambda *a: order.append('cap'))
    monkeypatch.setattr(R.subprocess, 'run',
                        lambda argv, **k: (order.append(argv[0]), types.SimpleNamespace(returncode=0))[1])
    r = R.Runner(escalator=_Stub(order, got=EACH_STEP))
    r.run('apk add a', sudo=True, capture=False)
    r.run('apk add b', sudo=True, capture=False)
    assert order == ['preauth', 'doas', 'doas']               # one note, then doas asks per op itself


def test_runner_detects_its_escalator_at_construction(monkeypatch):
    monkeypatch.setattr(privilege.os, 'geteuid', lambda: 0)
    assert type(R.Runner(pretend=True).escalator) is AlreadyRoot
    monkeypatch.setattr(privilege.os, 'geteuid', lambda: 1000)
    assert type(R.Runner(pretend=True).escalator) is Sudo     # conftest's fake sudo is on PATH
