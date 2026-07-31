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
