from configsys.runner import Runner, Result, _can_tee


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


def test_presudo_preauthenticates_before_teeing_then_stops_keepalive(monkeypatch):
    # the presudo FALLBACK (ctty disabled): sudo is pre-authenticated UN-teed and a keep-alive is
    # started BEFORE the tee, and stopped after — so the build's internal sudo never prompts inside
    # the tee (which deadlocks). Order matters. (ctty is the default; =0 selects this path.)
    from configsys import runner as R
    monkeypatch.setenv('CONFIGSYS_PTY_CTTY', '0')
    order = []
    monkeypatch.setattr(R, '_can_tee', lambda: True)
    monkeypatch.setattr(R, '_run_teed', lambda *a, **k: (order.append('tee'), (0, 'out'))[1])

    def fake_sub(argv, **kw):
        order.append('preauth' if argv[:1] == ['sudo'] else f'sub:{argv}')
        return type('C', (), {'returncode': 0})()
    monkeypatch.setattr(R.subprocess, 'run', fake_sub)

    class FakeStop:
        def set(self):
            order.append('keepalive-stop')
    monkeypatch.setattr(R, '_sudo_keepalive',
                        lambda: (order.append('keepalive-start'), FakeStop())[1])

    r = R.Runner()
    res = r.run('bash build.sh', capture=False, presudo=True)
    assert res.ok
    assert order == ['preauth', 'keepalive-start', 'tee', 'keepalive-stop']


def test_no_presudo_does_not_preauthenticate(monkeypatch):
    from configsys import runner as R
    order = []
    monkeypatch.setattr(R, '_can_tee', lambda: True)
    monkeypatch.setattr(R, '_run_teed', lambda *a, **k: (order.append('tee'), (0, ''))[1])
    monkeypatch.setattr(R.subprocess, 'run', lambda *a, **k: order.append('sub'))
    R.Runner().run('bash build.sh', capture=False)          # presudo defaults False
    assert order == ['tee']                                  # no pre-auth, no keepalive


def test_ctty_is_the_default_and_skips_presudo(monkeypatch):
    # baked in: with no env override the child gets the pty as its controlling terminal (ctty=True),
    # so presudo (pre-auth + keepalive) is NOT used even when the caller passes presudo=True.
    from configsys import runner as R
    monkeypatch.delenv('CONFIGSYS_PTY_CTTY', raising=False)
    order, seen = [], {}
    monkeypatch.setattr(R, '_can_tee', lambda: True)

    def fake_teed(argv, cwd, env, limit, ctty=False):
        seen['ctty'] = ctty
        order.append('tee')
        return (0, 'out')
    monkeypatch.setattr(R, '_run_teed', fake_teed)
    monkeypatch.setattr(R.subprocess, 'run', lambda *a, **k: order.append('preauth'))
    monkeypatch.setattr(R, '_sudo_keepalive', lambda: order.append('keepalive'))
    R.Runner().run('bash build.sh', capture=False, presudo=True)
    assert seen['ctty'] is True
    assert order == ['tee']                     # no pre-auth, no keepalive under ctty mode


def test_child_setctty_claims_controlling_terminal(monkeypatch):
    import termios
    from configsys import runner as R
    calls = []
    monkeypatch.setattr(R.fcntl, 'ioctl', lambda fd, req, arg=0: calls.append((fd, req, arg)))
    R._child_setctty()
    assert calls == [(0, termios.TIOCSCTTY, 0)]     # fd 0 (the pty slave) -> our controlling terminal


def _teed_popen_kwargs(monkeypatch, ctty):
    from configsys import runner as R
    import pty
    popen_kw = {}

    class _Sentinel(Exception):
        pass

    def fake_popen(argv, **kw):
        popen_kw.update(kw)
        raise _Sentinel()                        # stop before the io loop; we only inspect kwargs
    monkeypatch.setattr(pty, 'openpty', lambda: (10, 11))
    monkeypatch.setattr(R.os, 'close', lambda fd: None)
    monkeypatch.setattr(R.fcntl, 'ioctl', lambda *a, **k: b'\0' * 8)
    monkeypatch.setattr(R.subprocess, 'Popen', fake_popen)
    try:
        R._run_teed(['bash', '-c', 'x'], None, None, 1024, ctty=ctty)
    except _Sentinel:
        pass
    return popen_kw


def test_run_teed_ctty_gives_child_its_own_controlling_terminal(monkeypatch):
    kw = _teed_popen_kwargs(monkeypatch, ctty=True)
    from configsys import runner as R
    assert kw.get('start_new_session') is True and kw.get('preexec_fn') is R._child_setctty


def test_run_teed_without_ctty_shares_the_real_terminal(monkeypatch):
    kw = _teed_popen_kwargs(monkeypatch, ctty=False)
    assert 'start_new_session' not in kw and 'preexec_fn' not in kw
