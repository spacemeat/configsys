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
    for keys in (b'j', b'!', b'j', b'!', b'?', b'j', b'q', b' ', b'q', b'k', b'\n'):
        try:
            os.write(master, keys)
        except OSError:
            break
        # DRAIN while driving: truecolor + the help modal emit a lot of output; if we don't read the
        # PTY the buffer fills and curses blocks on write (looks like a hang).
        _drain(master, time.monotonic() + 0.15)

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


def test_tui_hierarchical_ballot_drilldown(tmp_path):
    '''Open the hierarchical drill-down ballot (enter on a derived aggregate profile), cycle a
    sub-unit, drill into it, edit a child, pop up, and exit — the A-hierarchical TUI path.'''
    try:
        master, slave = pty.openpty()
    except OSError:
        pytest.skip('no PTY available')

    cfg = tmp_path / '.config' / 'configsys' / 'configsys.hu'
    cfg.parent.mkdir(parents=True, exist_ok=True)
    # tl derives the repo `languages` aggregate -> its menu is sub-profile UNITS (drillable).
    cfg.write_text('{ configs: [ tl ]  profiles: { tl: [ "^languages" ] } }\n')

    env = dict(os.environ)
    env.update({'TERM': 'xterm-256color', 'CONFIGSYS_HOME': str(tmp_path),
                'CONFIGSYS_OS': 'pop', 'PYTHONPATH': str(REPO)})
    proc = subprocess.Popen(
        [sys.executable, '-m', 'configsys', '--pretend', 'tui'],
        stdin=slave, stdout=slave, stderr=slave, env=env, cwd=str(REPO), close_fds=True)
    os.close(slave)

    deadline = time.monotonic() + 10
    first = _drain(master, min(deadline, time.monotonic() + 3))
    # 2 -> Profiles; j -> the tl profile (under 'this machine'); ⏎ -> its ballot; space -> derive the
    # first sub-unit; l -> drill in; space -> pick a child; h -> up; q -> close ballot; then quit.
    for keys in (b'2', b'j', b'\n', b' ', b'l', b' ', b'h', b'q', b'q', b'k', b'\n'):
        try:
            os.write(master, keys)
        except OSError:
            break
        _drain(master, time.monotonic() + 0.2)

    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        os.close(master)
        pytest.fail('TUI did not exit')
    os.close(master)
    assert proc.returncode == 0
    assert first, 'TUI produced no terminal output'


def test_tui_machine_target_selector(tmp_path):
    '''Open the working-target machine picker (M) on the Profiles page, switch target to a defined
    machine (rebuilds against its rung + `machine:` group), edit into its namespace, then quit.'''
    try:
        master, slave = pty.openpty()
    except OSError:
        pytest.skip('no PTY available')

    cfg = tmp_path / '.config' / 'configsys' / 'configsys.hu'
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('{ machine: laptop  configs: [ finders ]  '
                   'machines: { laptop: { configs: [ finders ]  '
                   'profiles: { finders: [ "^finders"  fd ] } } } }\n')

    env = dict(os.environ)
    env.update({'TERM': 'xterm-256color', 'CONFIGSYS_HOME': str(tmp_path),
                'CONFIGSYS_OS': 'pop', 'PYTHONPATH': str(REPO)})
    proc = subprocess.Popen(
        [sys.executable, '-m', 'configsys', '--pretend', 'tui'],
        stdin=slave, stdout=slave, stderr=slave, env=env, cwd=str(REPO), close_fds=True)
    os.close(slave)

    deadline = time.monotonic() + 10
    first = _drain(master, min(deadline, time.monotonic() + 3))
    # 2 -> Profiles; M -> machine picker; j,⏎ -> target 'laptop'; j -> the finders row (under the
    # machine group); tab -> catalog; space -> edit into laptop's namespace; then quit.
    for keys in (b'2', b'M', b'j', b'\n', b'j', b'\t', b' ', b'q', b'k', b'\n'):
        try:
            os.write(master, keys)
        except OSError:
            break
        _drain(master, time.monotonic() + 0.2)

    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        os.close(master)
        pytest.fail('TUI did not exit')
    os.close(master)
    assert proc.returncode == 0
    assert first, 'TUI produced no terminal output'


def test_tui_renders_a_derived_profile_ballot(tmp_path):
    '''Render the Profiles page with a `^derive` profile selected + the catalog focused, so the ballot
    draw path (menu_new `?`/color, `^⁺N` badge, ballot title) runs without crashing in real curses.'''
    try:
        master, slave = pty.openpty()
    except OSError:
        pytest.skip('no PTY available')

    cfg = tmp_path / '.config' / 'configsys' / 'configsys.hu'
    cfg.parent.mkdir(parents=True, exist_ok=True)
    # `m` derives from `ai`: picks htop, offers bat (NEW `?`) — a real ballot to render.
    cfg.write_text('{ configs: [ m ]  profiles: { ai: [ htop  bat ]  m: [ "^ai"  htop ] } }\n')

    env = dict(os.environ)
    env.update({'TERM': 'xterm-256color', 'CONFIGSYS_HOME': str(tmp_path),
                'CONFIGSYS_OS': 'pop', 'PYTHONPATH': str(REPO)})
    proc = subprocess.Popen(
        [sys.executable, '-m', 'configsys', '--pretend', 'tui'],
        stdin=slave, stdout=slave, stderr=slave, env=env, cwd=str(REPO), close_fds=True)
    os.close(slave)

    deadline = time.monotonic() + 8
    first = _drain(master, min(deadline, time.monotonic() + 3))
    # 2 -> Profiles page; L,L exercises the flat<->grouped pane render then restores grouped (lcur
    # resets to 0); ai/m are user-layer profiles under the open 'this machine' group, so j,j lands on
    # m (the derive); tab -> focus catalog (ballot markers); j -> a cell; then quit.
    for keys in (b'2', b'L', b'L', b'j', b'j', b'\t', b'j', b'j', b'q', b'k', b'\n'):
        try:
            os.write(master, keys)
        except OSError:
            break
        _drain(master, time.monotonic() + 0.15)

    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        os.close(master)
        pytest.fail('TUI did not exit after q')
    os.close(master)
    assert proc.returncode == 0
    assert first, 'TUI produced no terminal output'


def test_tui_reconcile_overlay(tmp_path):
    '''Open the reconcile overlay (N) on an active derived profile with NEW items, pick one, toggle
    the auto-declined section, and close — the step-4 render + action path — then quit.'''
    try:
        master, slave = pty.openpty()
    except OSError:
        pytest.skip('no PTY available')

    cfg = tmp_path / '.config' / 'configsys' / 'configsys.hu'
    cfg.parent.mkdir(parents=True, exist_ok=True)
    # mine derives from ai and picks only htop -> bat/fd are OFFERED (NEW) -> the reconcile has content.
    cfg.write_text('{ configs: [ mine ]  profiles: { ai: [ htop  bat  fd ]  '
                   'mine: [ "^ai"  htop ] } }\n')

    env = dict(os.environ)
    env.update({'TERM': 'xterm-256color', 'CONFIGSYS_HOME': str(tmp_path),
                'CONFIGSYS_OS': 'pop', 'PYTHONPATH': str(REPO)})
    proc = subprocess.Popen(
        [sys.executable, '-m', 'configsys', '--pretend', 'tui'],
        stdin=slave, stdout=slave, stderr=slave, env=env, cwd=str(REPO), close_fds=True)
    os.close(slave)

    deadline = time.monotonic() + 10
    first = _drain(master, min(deadline, time.monotonic() + 3))
    # N -> reconcile overlay; space -> pick the first NEW; d -> decline the next; q -> close; then quit.
    for keys in (b'N', b' ', b'd', b'q', b'q', b'k', b'\n'):
        try:
            os.write(master, keys)
        except OSError:
            break
        _drain(master, time.monotonic() + 0.2)

    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        os.close(master)
        pytest.fail('TUI did not exit after q')
    os.close(master)
    assert proc.returncode == 0
    assert first, 'TUI produced no terminal output'


def test_tui_pin_or_track_modal_and_profile_where(tmp_path):
    '''Drive the Profiles page into the pin-or-track modal (editing a repo-only profile) and the
    `w` profile-where overlay — the step-3 render paths — then quit, all without crashing.'''
    try:
        master, slave = pty.openpty()
    except OSError:
        pytest.skip('no PTY available')

    cfg = tmp_path / '.config' / 'configsys' / 'configsys.hu'
    cfg.parent.mkdir(parents=True, exist_ok=True)
    # activate a repo catalog profile; it's defined only in config.hu, so a membership edit synthesizes
    # a first amend -> the pin-or-track modal fires (profile-edit-mode defaults to ask).
    cfg.write_text('{ configs: [ finders ] }\n')

    env = dict(os.environ)
    env.update({'TERM': 'xterm-256color', 'CONFIGSYS_HOME': str(tmp_path),
                'CONFIGSYS_OS': 'pop', 'PYTHONPATH': str(REPO)})
    proc = subprocess.Popen(
        [sys.executable, '-m', 'configsys', '--pretend', 'tui'],
        stdin=slave, stdout=slave, stderr=slave, env=env, cwd=str(REPO), close_fds=True)
    os.close(slave)

    deadline = time.monotonic() + 10
    first = _drain(master, min(deadline, time.monotonic() + 3))
    # 2 -> Profiles; the pane groups by layer with the repo catalog collapsed, so l unfolds it, j
    # lands on the first repo profile; w -> profile-where overlay, esc closes it; tab -> catalog;
    # space -> edit that repo-only profile -> pin-or-track modal; p -> choose PIN; then quit.
    for keys in (b'2', b'l', b'j', b'w', b'\x1b', b'\t', b' ', b'p', b'q', b'k', b'\n'):
        try:
            os.write(master, keys)
        except OSError:
            break
        _drain(master, time.monotonic() + 0.2)

    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        os.close(master)
        pytest.fail('TUI did not exit after q')
    os.close(master)
    assert proc.returncode == 0
    assert first, 'TUI produced no terminal output'
