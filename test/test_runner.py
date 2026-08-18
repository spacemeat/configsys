import os
import signal
import subprocess
import sys
import time

import pytest

from configsys.runner import Runner, Result, _can_tee


def test_captured_tty_raises_keyboardinterrupt_on_sigint(tmp_path):
    '''Ctrl-C during a captured sudo op must raise KeyboardInterrupt (so the install loop aborts the
    WHOLE batch), not just quietly kill this op and march on. Driven in a child process group so the
    SIGINT we send only hits it.'''
    prog = (
        'import sys; sys.path.insert(0, %r)\n'
        'from configsys import runner as R\n'
        'try:\n'
        '    R._run_captured_tty(["bash","-c","echo GO; sleep 30"], None, None, 65536)\n'
        '    print("NO_INTERRUPT", flush=True)\n'
        'except KeyboardInterrupt:\n'
        '    print("KBI", flush=True)\n'
    ) % os.getcwd()
    p = subprocess.Popen([sys.executable, '-c', prog], stdout=subprocess.PIPE, text=True,
                         start_new_session=True)            # own group -> we signal only it
    assert p.stdout.readline().strip() == 'GO'              # child's grandchild is running
    time.sleep(0.2)
    os.killpg(os.getpgid(p.pid), signal.SIGINT)             # Ctrl-C the whole group
    out = p.stdout.read()
    p.wait(timeout=10)
    assert 'KBI' in out and 'NO_INTERRUPT' not in out


@pytest.mark.skipif(not hasattr(os, 'fork') or not hasattr(os, 'openpty'),
                    reason='needs fork + pty')
def test_run_teed_forwards_sigint_to_child(tmp_path):
    '''A Ctrl-C typed at the terminal MUST reach the teed child (the old sudo/tee attempt wedged
    because SIGINT went inert). The child owns the pty as its controlling terminal with ISIG on, so
    the forwarded `\\x03` byte becomes a SIGINT to it — proven here by driving _run_teed's stdio on a
    real pty and "typing" Ctrl-C.'''
    import pty
    import select
    import sys
    import time
    from configsys import runner as R

    got, rcf = tmp_path / 'got', tmp_path / 'rc'
    master, slave = pty.openpty()
    pid = os.fork()
    if pid == 0:                                          # child: pty slave = our stdio, then tee
        try:
            os.setsid()
            for fd in (0, 1, 2):
                os.dup2(slave, fd)
            os.close(master); os.close(slave)
            sys.stdin = os.fdopen(0, 'r')                 # drop pytest's capture: _run_teed reads
            sys.stdout = os.fdopen(1, 'w')                # sys.stdin/out.fileno() -> the pty fds
            sys.stderr = os.fdopen(2, 'w')
            inner = ("import signal,sys,time\n"
                     f"signal.signal(signal.SIGINT, lambda *a:(open({str(got)!r},'w').write('INT'),"
                     " sys.exit(42)))\n"
                     "sys.stdout.write('READY\\n'); sys.stdout.flush()\n"
                     "time.sleep(10)\n")
            rc, _tail = R._run_teed(['python3', '-c', inner], None, None, 65536)
            rcf.write_text(str(rc))
        finally:
            os._exit(0)
    os.close(slave)
    buf, t0 = b'', time.time()
    while b'READY' not in buf and time.time() - t0 < 8:
        if master in select.select([master], [], [], 0.5)[0]:
            try:
                buf += os.read(master, 1024)
            except OSError:
                break
    os.write(master, b'\x03')                             # the Ctrl-C keystroke
    os.waitpid(pid, 0)
    os.close(master)
    for _ in range(20):                                   # let the child flush its marker
        if got.exists():
            break
        time.sleep(0.1)
    assert got.exists() and got.read_text() == 'INT'      # the teed child got SIGINT
    assert rcf.read_text() == '42'                        # ...and ran its handler (exit 42)


def test_pretend_records_and_does_not_execute():
    logged = []
    r = Runner(pretend=True, echo=logged.append)
    res = r.run('rm -rf /definitely/not/real')
    assert res.pretended and res.ok
    assert r.calls == ['rm -rf /definitely/not/real']
    assert logged == ['[pretend] rm -rf /definitely/not/real']


def test_pretend_prefixes_sudo():
    r = Runner(pretend=True)
    r.run('apt-get install btop', sudo=True)
    assert r.calls == ['sudo apt-get install btop']


def test_real_capture():
    r = Runner(pretend=False)
    res = r.run('printf hello')
    assert res.ok
    assert res.stdout == 'hello'


def test_real_nonzero_returncode():
    r = Runner(pretend=False)
    res = r.run('exit 3')
    assert res.returncode == 3
    assert not res.ok


def test_compound_failure_propagates_with_set_e():
    # a multi-line script's failure must be reported (not masked by a later `|| true`)
    r = Runner(pretend=False)
    res = r.run('set -e\nfalse\nexit 0')
    assert not res.ok and res.returncode != 0


def test_sudo_runs_whole_command_in_one_root_shell(monkeypatch):
    captured = {}

    class CP:
        returncode, stdout, stderr = 0, '', ''

    def fake_run(argv, **kw):
        captured['argv'] = argv
        return CP()

    monkeypatch.setattr('configsys.runner.subprocess.run', fake_run)
    r = Runner(pretend=False)
    r.run('mkdir -p /x && curl y', sudo=True)
    # the WHOLE compound runs under one root shell (not `sudo mkdir && curl`)
    assert captured['argv'] == ['sudo', 'bash', '-c', 'mkdir -p /x && curl y']
    assert r.calls == ['sudo mkdir -p /x && curl y']   # readable form unchanged


def test_nonsudo_runs_in_plain_shell(monkeypatch):
    captured = {}

    class CP:
        returncode, stdout, stderr = 0, '', ''

    def fake_run(argv, **kw):
        captured['argv'] = argv
        return CP()

    monkeypatch.setattr('configsys.runner.subprocess.run', fake_run)
    Runner(pretend=False).run('printf hi')
    assert captured['argv'] == ['bash', '-c', 'printf hi']


def test_streamed_op_without_tty_falls_back_to_plain(monkeypatch):
    # capture=False on a non-tty (tests, pipes) must NOT try to tee — plain streaming, no capture
    calls = {}

    class CP:
        returncode, stdout, stderr = 3, '', ''

    def fake_run(argv, **kw):
        calls['teed'] = False
        return CP()

    def boom(*a, **k):
        calls['teed'] = True
        raise AssertionError('should not tee without a tty')

    monkeypatch.setattr('configsys.runner.subprocess.run', fake_run)
    monkeypatch.setattr('configsys.runner._run_teed', boom)
    res = Runner(pretend=False).run('make; exit 3', capture=False)
    assert res.returncode == 3 and res.captured == '' and calls['teed'] is False


def test_result_output_prefers_captured_when_streamed():
    assert Result('c', 0, stdout='real out').output == 'real out'
    assert Result('c', 2, captured='build tail\n').output == 'build tail'
    assert Result('c', 0).output == ''


def test_result_fail_carries_reason_in_stderr():
    r = Result.fail('no release asset matched `x`')
    assert not r.ok and r.returncode == 1
    assert r.cmd == ''                                   # no spurious command in the report
    assert r.stderr == 'no release asset matched `x`' and r.output == 'no release asset matched `x`'
    assert Result.fail('gone', returncode=3).returncode == 3


def test_can_tee_false_off_tty():
    # under pytest stdin/stdout are not ttys -> tee is disabled (guards the fallback above)
    assert _can_tee() is False


def test_run_works_from_a_worker_thread():
    '''Regression: the startup-splash runs inspection on a background thread, so every command
    goes through terminal_released off the main thread. signal.signal() raises there, which used
    to fail EVERY component probe — guard it so a worker-thread run still succeeds.'''
    import threading

    box = {}

    def work():
        try:
            box['res'] = Runner(pretend=False).run('printf ok')
        except BaseException as e:  # noqa: BLE001 — capture to assert on the main thread
            box['exc'] = e

    t = threading.Thread(target=work)
    t.start()
    t.join()
    assert 'exc' not in box, f'run() raised off the main thread: {box.get("exc")!r}'
    assert box['res'].ok and box['res'].stdout.strip() == 'ok'


def test_terminal_released_is_a_noop_off_the_main_thread(monkeypatch):
    '''Regression: the background inspection worker must not touch the tty — its termios
    save/restore raced the main thread's curses setup and dropped the TUI into cooked/echo mode
    (keys echoed, needed Enter). Off the main thread the context touches neither termios nor
    signals.'''
    import threading
    from configsys import runner as R

    calls = []
    monkeypatch.setattr(R.termios, 'tcgetattr', lambda fd: calls.append('tcgetattr'))
    monkeypatch.setattr(R.termios, 'tcsetattr', lambda fd, when, a: calls.append('tcsetattr'))
    monkeypatch.setattr(R.signal, 'signal', lambda *a: calls.append('signal'))

    def work():
        with R.terminal_released(True):   # tui_active=True: would write escapes/termios on main
            pass

    t = threading.Thread(target=work)
    t.start()
    t.join()
    assert calls == []


def test_teed_plain_stream_does_not_preauth(monkeypatch):
    # A plain unprivileged streamed op tees with NO sudo pre-auth (nothing needs elevation).
    from configsys import runner as R
    order = []
    monkeypatch.setattr(R, '_can_tee', lambda: True)
    monkeypatch.setattr(R, '_sudo_preauth', lambda: order.append('preauth') or True)
    monkeypatch.setattr(R, '_run_teed', lambda *a: (order.append('tee'), (0, 'out'))[1])
    monkeypatch.setattr(R.subprocess, 'run', lambda *a, **k: order.append('sub'))
    res = R.Runner().run('echo hi', capture=False)
    assert res.ok and res.captured == 'out' and order == ['tee']   # tee only, no pre-auth


def test_sudo_op_preauths_then_captures_on_real_tty(monkeypatch):
    # A privileged streamed op pre-authenticates sudo ONCE (warming the real-tty ticket) then runs on
    # the REAL tty, capturing stdout via a pipe — NOT a pty. Under tty_tickets a pty'd op would be a
    # different tty and re-prompt every op; the real-tty run reuses the ticket and its output is still
    # captured for reports.
    import types
    from configsys import runner as R
    order = []
    monkeypatch.setattr(R, '_can_tee', lambda: True)
    monkeypatch.setattr(R, '_sudo_preauth', lambda: (order.append('preauth'), True)[1])
    monkeypatch.setattr(R, '_SudoKeepalive',
                        lambda: types.SimpleNamespace(stop=lambda: order.append('stop')))
    monkeypatch.setattr(R, '_run_captured_tty', lambda *a: (order.append('cap'), (0, 'apt output'))[1])
    monkeypatch.setattr(R, '_run_teed', lambda *a: order.append('tee'))          # must NOT fire for sudo
    monkeypatch.setattr(R.subprocess, 'run', lambda *a, **k: order.append('sub'))   # plain must NOT fire
    r = R.Runner()
    res = r.run('apt-get install -y sysdig', sudo=True, capture=False)
    assert res.ok and res.captured == 'apt output'   # sudo output captured
    assert order == ['preauth', 'cap']               # pre-auth -> captured-tty; keep-alive persists
    r.end_sudo()
    assert order == ['preauth', 'cap', 'stop']       # released at the end of the batch


def test_sudo_batch_preauths_once_across_ops(monkeypatch):
    # The fix for the prompt cascade: a whole batch of sudo ops prompts AT MOST ONCE — the credential
    # is warmed on the first op and reused (tty_tickets ticket on the real tty) for the rest.
    import types
    from configsys import runner as R
    order = []
    monkeypatch.setattr(R, '_can_tee', lambda: True)
    monkeypatch.setattr(R, '_sudo_preauth', lambda: (order.append('preauth'), True)[1])
    monkeypatch.setattr(R, '_SudoKeepalive', lambda: types.SimpleNamespace(stop=lambda: None))
    monkeypatch.setattr(R, '_run_captured_tty', lambda *a: (0, 'out'))
    r = R.Runner()
    for pkg in ('a', 'b', 'c'):
        r.run(f'apt-get install -y {pkg}', sudo=True, capture=False)
    assert order.count('preauth') == 1               # one prompt for the whole batch, not per op


def test_sudo_falls_back_to_plain_when_preauth_fails(monkeypatch):
    # If the credential can't be cached (user cancels), a sudo op skips the captured-tty path and
    # takes the plain inherited-stdio path (which may re-prompt) — never a wedge, never a broken run.
    import types
    from configsys import runner as R
    order = []
    monkeypatch.setattr(R, '_can_tee', lambda: True)
    monkeypatch.setattr(R, '_sudo_preauth', lambda: (order.append('preauth'), False)[1])
    monkeypatch.setattr(R, '_run_captured_tty', lambda *a: (order.append('cap'), (0, 'x'))[1])  # NOT fire
    monkeypatch.setattr(R, '_run_teed', lambda *a: order.append('tee'))                          # NOT fire
    monkeypatch.setattr(R.subprocess, 'run',
                        lambda *a, **k: (order.append('sub'), types.SimpleNamespace(returncode=0))[1])
    res = R.Runner().run('apt-get install -y sysdig', sudo=True, capture=False)
    assert order == ['preauth', 'sub'] and res.returncode == 0   # no captured-tty; plain path ran


def test_child_setctty_claims_controlling_terminal(monkeypatch):
    import termios
    from configsys import runner as R
    calls = []
    monkeypatch.setattr(R.fcntl, 'ioctl', lambda fd, req, arg=0: calls.append((fd, req, arg)))
    R._child_setctty()
    assert calls == [(0, termios.TIOCSCTTY, 0)]     # fd 0 (the pty slave) -> our controlling terminal


def test_run_teed_always_gives_child_its_own_controlling_terminal(monkeypatch):
    # unconditional: the teed child always gets start_new_session + the TIOCSCTTY preexec.
    from configsys import runner as R
    import pty
    popen_kw = {}

    class _Sentinel(Exception):
        pass

    def fake_popen(argv, **kw):
        popen_kw.update(kw)
        raise _Sentinel()                            # stop before the io loop; inspect kwargs only
    monkeypatch.setattr(pty, 'openpty', lambda: (10, 11))
    monkeypatch.setattr(R.os, 'close', lambda fd: None)
    monkeypatch.setattr(R.fcntl, 'ioctl', lambda *a, **k: b'\0' * 8)
    monkeypatch.setattr(R.subprocess, 'Popen', fake_popen)
    try:
        R._run_teed(['bash', '-c', 'x'], None, None, 1024)
    except _Sentinel:
        pass
    assert popen_kw.get('start_new_session') is True and popen_kw.get('preexec_fn') is R._child_setctty


def test_run_term_guards_runs_lifo_and_clears():
    from configsys import runner as R
    R._TERM_GUARDS.clear()
    order = []
    R._TERM_GUARDS.append(lambda: order.append('a'))
    R._TERM_GUARDS.append(lambda: order.append('b'))
    R._run_term_guards()
    assert order == ['b', 'a'] and R._TERM_GUARDS == []   # LIFO, then empty


def test_term_guard_deregisters_on_normal_exit():
    from configsys import runner as R
    sentinel = lambda: None                               # noqa: E731
    with R._term_guard(sentinel):
        assert sentinel in R._TERM_GUARDS
    assert sentinel not in R._TERM_GUARDS                 # gone on clean unwind -> no fire at atexit


def test_terminal_released_restores_termios_on_a_fatal_signal(monkeypatch):
    # SIGTERM/SIGHUP bypass the `finally`; the registered guard must still reset termios so the
    # terminal isn't left in the raw mode a teed child put it in.
    import types
    from configsys import runner as R
    monkeypatch.setattr(R.sys, 'stdin', types.SimpleNamespace(fileno=lambda: 0))
    monkeypatch.setattr(R.os, 'isatty', lambda fd: True)
    monkeypatch.setattr(R.termios, 'tcgetattr', lambda fd: ['SAVED'])
    restored = []
    monkeypatch.setattr(R.termios, 'tcsetattr', lambda fd, when, attrs: restored.append(attrs))
    with R.terminal_released(False):
        R._run_term_guards()                              # simulate the fatal signal firing mid-child
    assert ['SAVED'] in restored                          # termios reset to the saved (sane) attrs
