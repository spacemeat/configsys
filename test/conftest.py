'''Shared pytest fixtures and path setup.

Ensures the repo root is importable (so `import configsys...` works without an
installed package). Shared test doubles and builders live in test/fakes.py; the `primary` fixture
(a blessed primary with a bare remote and a second clone) is built on its `primary_remote`.

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
- No network from the test process: a socket connect to anything but loopback or a unix socket
  raises `NetworkDisabledError` (an OSError, so version discovery reads it as offline) unless the
  test is marked `@pytest.mark.network` — the suite never spends your api.github.com rate limit
  or depends on what a remote serves (review-2026-11-2 tests-tools-04).
'''

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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


class NetworkDisabledError(OSError):
    '''A test opened a network connection without `@pytest.mark.network`.'''


def _local(address):
    if not isinstance(address, tuple):              # AF_UNIX path
        return True
    host = str(address[0])
    return host in ('localhost', '::1') or host.startswith('127.')


def pytest_configure(config):
    config.addinivalue_line(
        'markers', 'real_runner: the test executes real commands through configsys.runner.Runner '
                   '(git, curl file://, shells) — never sudo')
    config.addinivalue_line(
        'markers', 'network: the test may open network connections (off by default)')


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

    from configsys import routes as _routes            # no facet probe answer leaks between tests
    _routes.clear_facet_cache()
    from configsys import runner as _runner
    real_run = _runner.Runner.run
    allowed = request.node.get_closest_marker('real_runner') is not None

    def guarded_run(self, cmd, *a, **kw):
        if not self.pretend and not allowed:
            raise RealRunnerError(f'real Runner.run in a test: {cmd!r} — use --pretend / a fake '
                                  'runner, or mark the test @pytest.mark.real_runner')
        return real_run(self, cmd, *a, **kw)

    monkeypatch.setattr(_runner.Runner, 'run', guarded_run)

    if request.node.get_closest_marker('network') is None:
        import socket
        real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex

        def guarded_connect(sock, address):
            if not _local(address):
                raise NetworkDisabledError(f'network disabled in tests: connect to {address!r} '
                                           '(mark the test @pytest.mark.network)')
            return real_connect(sock, address)

        def guarded_connect_ex(sock, address):
            if not _local(address):
                raise NetworkDisabledError(f'network disabled in tests: connect to {address!r}')
            return real_connect_ex(sock, address)
        real_getaddrinfo = socket.getaddrinfo

        def guarded_getaddrinfo(host, *a, **kw):        # DNS happens in C, before any connect
            if host is not None and not _local((host,)):
                raise NetworkDisabledError(f'network disabled in tests: resolve {host!r}')
            return real_getaddrinfo(host, *a, **kw)
        monkeypatch.setattr(socket.socket, 'connect', guarded_connect)
        monkeypatch.setattr(socket.socket, 'connect_ex', guarded_connect_ex)
        monkeypatch.setattr(socket, 'getaddrinfo', guarded_getaddrinfo)
        from configsys import versions as _versions          # no backoff sleeps on a refused fetch
        monkeypatch.setattr(_versions, '_RETRY_DELAYS', tuple(0 for _ in _versions._RETRY_DELAYS))
    yield
    if sudo_log.exists():
        pytest.fail(f'the test ran sudo (blocked by test/conftest.py): {sudo_log.read_text()!r}')


@pytest.fixture
def primary(tmp_path):
    '''A sandbox home with a blessed primary `prim` cloned from bare remote `bare`, plus `other`: a
    second clone standing in for your other machine. -> (base argv, clone, bare, other). A module
    that needs a different primary defines its own `primary` fixture, which overrides this one.'''
    from fakes import BASE_P, primary_remote
    return primary_remote(tmp_path, {'p.hu': BASE_P, 'notes.txt': BASE_P},   # notes: git's line merge only
                          seed='other')
