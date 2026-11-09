'''test/fakes.py's FakeRunner keeps up with the real Runner (review-2026-11-2 tests-tools-15): thirty
hand-copied fakes each hard-coded `Runner.run`'s keywords, so none accepted `presudo` and most had no
`.pretend` — one shared fake, checked against the real signature here, can't drift that way.'''

import inspect

from configsys.runner import Runner

from fakes import FakeRunner

_REAL_RUN = Runner.run          # bound at import: conftest's `_hermetic` swaps in a guard per test

def test_fake_runner_matches_runner_signature():
    assert _REAL_RUN.__qualname__ == "Runner.run"
    real = inspect.signature(_REAL_RUN).parameters
    fake = inspect.signature(FakeRunner.run).parameters
    missing = [n for n in real if n not in fake]
    assert not missing, f'FakeRunner.run lacks Runner.run parameters: {missing}'
    for name, p in real.items():
        if name in ('self', 'cmd'):
            continue
        assert fake[name].kind == p.kind and fake[name].default == p.default, name


def test_fake_runner_has_what_drivers_read_off_a_runner():
    fr = FakeRunner()
    assert fr.pretend is False
    fr.echo('a note')                                   # a no-op, like the real runner's under test


def test_fake_runner_matches_by_substring_and_records_sudo():
    fr = FakeRunner([('dpkg-query', 0, 'ii btop 1.0')])
    assert fr.run('dpkg-query -W btop').stdout == 'ii btop 1.0'
    assert fr.run('apt-get install -y btop', sudo=True, presudo=True).returncode == 0
    assert fr.calls == ['dpkg-query -W btop', 'sudo apt-get install -y btop']
