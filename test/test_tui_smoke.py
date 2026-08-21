'''Smoke test: launch the real curses TUI under a pseudo-terminal, drive a few
keys, and quit. Verifies init/render/teardown don't crash and the terminal is
restored (endwin runs). Skipped if a PTY can't be allocated.'''

import os
import pty
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _drain(fd, deadline):
    buf = b''
    while time.monotonic() < deadline:
        r, _, _ = select.select([fd], [], [], 0.1)
        if r:
            try:
                data = os.read(fd, 4096)
            except OSError:
                break
            if not data:
                break
            buf += data
        else:
            if buf:
                break
    return buf


@pytest.mark.parametrize('extra', [[], ['--nocolor'], ['--color', '16'], ['--color', '8']],
                         ids=['color', 'nocolor', 'color16', 'color8'])
def test_tui_launches_navigates_and_quits(tmp_path, extra):
    try:
        master, slave = pty.openpty()
    except OSError:
        pytest.skip('no PTY available')

    # pre-create the user config so first-run onboarding (the primary-plugin prompt) doesn't
    # fire under the PTY and consume the TUI keystrokes — this test is about TUI nav, not setup.
    # an active profile with an unroutable component -> a real diagnostic, so the `!` page has
    # content to render (a resilient error row, not a brick).
    cfg = tmp_path / '.config' / 'configsys' / 'configsys.hu'
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('{ configs: [ mine ]  profiles: { mine: [ ghost-tool ] } }\n')

    env = dict(os.environ)
    env.update({
        'TERM': 'xterm-256color',
        'CONFIGSYS_HOME': str(tmp_path),
        'CONFIGSYS_OS': 'pop',
        'PYTHONPATH': str(REPO),
    })
    proc = subprocess.Popen(
        [sys.executable, '-m', 'configsys', '--pretend', *extra, 'tui'],
        stdin=slave, stdout=slave, stderr=slave, env=env, cwd=str(REPO),
        close_fds=True,
    )
    os.close(slave)

    deadline = time.monotonic() + 8
    first = _drain(master, min(deadline, time.monotonic() + 3))
    # drive: down, open diagnostics page, scroll, close it, select, then quit — `q` opens a
    # "Really quit?" modal (default No), so `k` moves to "Yes, quit" and Enter confirms. Runs in
    # three color modes (auto / --nocolor / --color 16) so a low-color render crash can't slip in.
    for keys in (b'j', b'!', b'j', b'!', b' ', b'q', b'k', b'\n'):
        try:
            os.write(master, keys)
        except OSError:
            break
        time.sleep(0.15)

    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        os.close(master)
        pytest.fail('TUI did not exit after q')

    os.close(master)
    assert proc.returncode == 0
    # curses drew something (alt-screen or SGR); at minimum it produced output.
    assert first, 'TUI produced no terminal output'
