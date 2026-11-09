'''Shared pytest fixtures and path setup.

Ensures the repo root is importable (so `import configsys...` works without an
installed package) and provides a fixtures directory helper.

Every test is HERMETIC by default (`_hermetic`, autouse — review-2026-11-2 A17): it can't reach the
developer's machine through configsys or git.
- `HOME` is a fresh temp dir and every inherited `CONFIGSYS_*` / `XDG_*` variable is dropped, so
  `--home` can't lose to an exported `CONFIGSYS_STATE_DIR` and no test edits the real config.
- git ignores the developer's global/system config (`GIT_CONFIG_GLOBAL=/dev/null`) and commits as a
  fixed identity, so a `commit.gpgsign` setup neither breaks the fixtures nor signs throwaway
  commits with a real key.
- A fake `sudo` sits first on PATH: it exits 1 and logs its argv, and a test that reached it fails
  — no password prompt mid-suite, no `apt-get update` as root.
- `Runner.run` refuses to execute (raises `RealRunnerError`) unless the runner is `--pretend` or
  the test is marked `@pytest.mark.real_runner` (it needs real git / `curl file://` / shells).
'''

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FIXTURES = Path(__file__).resolve().parent / 'fixtures'

_FAKE_SUDO = '''#!/bin/sh
# configsys test suite: sudo is disabled (test/conftest.py). Log the attempt and fail.
printf '%s\\n' "$*" >> "$CONFIGSYS_TEST_SUDO_LOG"
echo "sudo: disabled under the configsys test suite" >&2
exit 1
'''

_GIT_IDENTITY = {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
                 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}


# test-suite switches (not configsys settings) that survive the scrub
_TEST_CONTROLS = frozenset({'CONFIGSYS_REGEN_GOLDEN'})


class RealRunnerError(RuntimeError):
    '''A test reached a real (non-pretend) Runner.run without `@pytest.mark.real_runner`.'''


def pytest_configure(config):
    config.addinivalue_line(
        'markers', 'real_runner: the test executes real commands through configsys.runner.Runner '
                   '(git, curl file://, shells) — never sudo')


@pytest.fixture(scope='session')
def _fake_sudo_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp('fakesudo')
    sudo = d / 'sudo'
    sudo.write_text(_FAKE_SUDO)
    sudo.chmod(0o755)
    return d


@pytest.fixture(autouse=True)
def _hermetic(request, monkeypatch, tmp_path_factory, _fake_sudo_dir):
    for name in list(os.environ):
        if name.startswith(('CONFIGSYS_', 'XDG_')) and name not in _TEST_CONTROLS:
            monkeypatch.delenv(name, raising=False)
    home = tmp_path_factory.mktemp('home')
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    for k, v in _GIT_IDENTITY.items():
        monkeypatch.setenv(k, v)
    sudo_log = home.parent / f'{home.name}.sudo.log'
    monkeypatch.setenv('CONFIGSYS_TEST_SUDO_LOG', str(sudo_log))
    monkeypatch.setenv('PATH', f'{_fake_sudo_dir}{os.pathsep}{os.environ.get("PATH", "")}')

    from configsys import runner as _runner
    real_run = _runner.Runner.run
    allowed = request.node.get_closest_marker('real_runner') is not None

    def guarded_run(self, cmd, *a, **kw):
        if not self.pretend and not allowed:
            raise RealRunnerError(f'real Runner.run in a test: {cmd!r} — use --pretend / a fake '
                                  'runner, or mark the test @pytest.mark.real_runner')
        return real_run(self, cmd, *a, **kw)

    monkeypatch.setattr(_runner.Runner, 'run', guarded_run)
    yield
    if sudo_log.exists():
        pytest.fail(f'the test ran sudo (blocked by test/conftest.py): {sudo_log.read_text()!r}')


@pytest.fixture
def fixtures_dir():
    return FIXTURES
