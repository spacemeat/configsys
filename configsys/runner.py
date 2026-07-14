'''runner.py — the single subprocess chokepoint for the whole app.

Every shell-out goes through Runner.run so that:
  * --pretend/dry-run can print commands instead of executing them (safe on the
    host, and makes command construction assertable in tests),
  * the terminal can be released cleanly when shelling out from inside the curses
    TUI (so sudo/apt can prompt and paint normally),
  * tests can inject a recording/mock runner.
'''

import os
import signal
import subprocess
import sys
import termios
from contextlib import contextmanager


@contextmanager
def terminal_released(tui_active: bool):
    '''Temporarily hand the terminal back to a child process. When the TUI is
    active, leave the alternate screen / restore sane modes first, then restore
    them afterward. A no-op (beyond SIGINT forwarding) when no TUI is running.'''
    try:
        fd = sys.stdin.fileno()
        isatty = os.isatty(fd)
    except (OSError, ValueError, AttributeError):
        # stdin may be a pipe or a pytest pseudofile with no real fd.
        fd, isatty = None, False
    saved = termios.tcgetattr(fd) if isatty else None

    if tui_active:
        sys.stdout.write(
            '\x1b[?1049l'                        # leave alternate screen
            '\x1b[?25h'                          # show cursor
            '\x1b[0m'                            # reset SGR
            '\x1b[?7h'                           # re-enable line wrap
            '\x1b[?1000l\x1b[?1002l\x1b[?1006l'  # mouse reporting off
            '\x1b[?2004l'                        # bracketed paste off
        )
        sys.stdout.flush()

    old_int = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, old_int)
        if isatty and saved is not None:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        if tui_active:
            sys.stdout.write('\x1b[?1049h')  # re-enter alternate screen
            sys.stdout.flush()


class Result:
    '''Uniform command result (mirrors the bits of CompletedProcess we use).'''

    def __init__(self, cmd, returncode, stdout='', stderr='', pretended=False):
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout or ''
        self.stderr = stderr or ''
        self.pretended = pretended

    @property
    def ok(self):
        return self.returncode == 0


class Runner:
    def __init__(self, pretend=False, echo=None):
        self.pretend = pretend
        self._echo = echo
        self.tui_active = False  # set by the app while the curses TUI owns the screen
        self.calls = []  # every full command string, in order (for tests/logs)

    def echo(self, msg):
        if self._echo:
            self._echo(msg)

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None,
            cwd=None, env=None) -> Result:
        full = f'sudo {cmd}' if sudo else cmd
        self.calls.append(full)

        if self.pretend:
            self.echo(f'[pretend] {full}')
            return Result(full, 0, pretended=True)

        ta = self.tui_active if tui_active is None else tui_active
        with terminal_released(ta):
            cp = subprocess.run(
                ['bash', '-c', full],
                capture_output=capture, text=True, cwd=cwd, env=env,
            )
        return Result(full, cp.returncode,
                      stdout=cp.stdout if capture else '',
                      stderr=cp.stderr if capture else '')
