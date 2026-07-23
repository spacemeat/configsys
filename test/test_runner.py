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


def test_can_tee_false_off_tty():
    # under pytest stdin/stdout are not ttys -> tee is disabled (guards the fallback above)
    assert _can_tee() is False
