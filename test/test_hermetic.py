'''The suite's hermetic guard itself (test/conftest.py, review-2026-11-2 A17): no test reaches the
developer's machine through configsys's runner, sudo, git config or an exported CONFIGSYS_* var.'''

import os
import subprocess
from pathlib import Path

import pytest

from configsys.runner import Runner


def test_a_real_runner_call_is_refused_without_the_marker():
    from conftest import RealRunnerError
    with pytest.raises(RealRunnerError):
        Runner().run('true')
    assert Runner(pretend=True).run('apt-get update', sudo=True).ok     # pretend is always fine


@pytest.mark.real_runner
def test_the_marker_allows_real_commands_but_sudo_is_a_fake():
    assert Runner().run('echo hi').stdout.strip() == 'hi'
    r = subprocess.run(['sudo', '-n', 'true'], capture_output=True, text=True)
    assert r.returncode == 1 and 'disabled under the configsys test suite' in r.stderr
    Path(os.environ['CONFIGSYS_TEST_SUDO_LOG']).unlink()               # (else this test fails itself)


def test_home_and_git_and_configsys_env_are_sandboxed():
    assert Path(os.environ['HOME']) != Path('/home') and 'pytest' in os.environ['HOME']
    assert os.environ['GIT_CONFIG_GLOBAL'] == os.devnull and os.environ['GIT_CONFIG_NOSYSTEM'] == '1'
    assert not [k for k in os.environ if k.startswith('CONFIGSYS_') and k != 'CONFIGSYS_TEST_SUDO_LOG']
    assert not [k for k in os.environ if k.startswith('XDG_')]
