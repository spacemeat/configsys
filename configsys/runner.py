'''runner.py — the single subprocess chokepoint for the whole app.

Every shell-out goes through Runner.run so that:
  * --pretend/dry-run can print commands instead of executing them (safe on the
    host, and makes command construction assertable in tests),
  * the terminal can be released cleanly when shelling out from inside the curses
    TUI (so sudo/apt can prompt and paint normally),
  * tests can inject a recording/mock runner.
'''

import os
import select
import signal
import subprocess
import sys
import termios
import tty
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

    def __init__(self, cmd, returncode, stdout='', stderr='', pretended=False, captured=''):
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout or ''
        self.stderr = stderr or ''
        self.pretended = pretended
        self.captured = captured or ''   # tee'd tail of streamed output (capture=False builds)

    @property
    def ok(self):
        return self.returncode == 0

    @property
    def output(self):
        '''The best available command output: captured stdout/stderr, else the tee'd tail.'''
        return (self.stdout + self.stderr).strip() or self.captured.strip()


def _can_tee():
    '''True when we can run a streamed child through a pty and mirror its output: needs a
    real controlling terminal on both ends (tests/pipes fall back to plain streaming).'''
    if not hasattr(os, 'openpty'):
        return False
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _run_teed(argv, cwd, env, limit):
    '''Run argv with its stdio on a pty: stream output to the real terminal live while
    retaining the last `limit` bytes, and forward the user's keystrokes to the child (so an
    interactive build still works). Returns (returncode, captured_tail). The child sees a tty,
    so colour/progress behave as normal. Used only for unprivileged streamed ops — a `sudo`
    password prompt goes to /dev/tty and is deliberately left off this path.'''
    import pty
    master, slave = pty.openpty()
    try:                                        # match the child pty to the real window size
        import fcntl
        sz = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b'\0' * 8)
        fcntl.ioctl(master, termios.TIOCSWINSZ, sz)
    except Exception:                           # noqa: BLE001 — best effort
        pass
    try:
        proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave,
                                cwd=cwd, env=env, close_fds=True)
    finally:
        os.close(slave)
    in_fd = sys.stdin.fileno()
    old = None
    try:
        old = termios.tcgetattr(in_fd)
        tty.setraw(in_fd)                       # child pty owns echo/line-editing -> single echo
    except Exception:                           # noqa: BLE001
        old = None
    tail = bytearray()
    try:
        while True:
            try:
                rlist, _, _ = select.select([master, in_fd], [], [])
            except (InterruptedError, OSError):
                continue
            if master in rlist:
                try:
                    data = os.read(master, 4096)
                except OSError:                 # EIO on Linux once the child exits == EOF
                    data = b''
                if not data:
                    break
                os.write(sys.stdout.fileno(), data)
                tail.extend(data)
                if len(tail) > limit:
                    del tail[:len(tail) - limit]
            if in_fd in rlist:
                try:
                    inp = os.read(in_fd, 4096)
                except OSError:
                    inp = b''
                if inp:
                    try:
                        os.write(master, inp)
                    except OSError:
                        pass
    finally:
        if old is not None:
            try:
                termios.tcsetattr(in_fd, termios.TCSADRAIN, old)
            except Exception:                   # noqa: BLE001
                pass
        os.close(master)
    text = tail.decode('utf-8', 'replace').replace('\r\n', '\n')   # de-pty the line endings
    return proc.wait(), text


class Runner:
    def __init__(self, pretend=False, echo=None):
        self.pretend = pretend
        self._echo = echo
        self.tui_active = False  # set by the app while the curses TUI owns the screen
        self.calls = []  # every full command string, in order (for tests/logs)
        self.tee_limit = 64 * 1024  # bytes of streamed output retained for failure reports

    def echo(self, msg):
        if self._echo:
            self._echo(msg)

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None,
            cwd=None, env=None) -> Result:
        full = f'sudo {cmd}' if sudo else cmd    # readable form for logs/tests
        self.calls.append(full)

        if self.pretend:
            self.echo(f'[pretend] {full}')
            return Result(full, 0, pretended=True)

        # Run the WHOLE command under one shell — and, when privileged, under one
        # root shell (`sudo bash -c '<cmd>'`). Prepending `sudo ` to a compound
        # command would only elevate its first word and eat a leading `set -e`.
        argv = ['sudo', 'bash', '-c', cmd] if sudo else ['bash', '-c', cmd]
        ta = self.tui_active if tui_active is None else tui_active
        with terminal_released(ta):
            # Unprivileged streamed op on a real terminal: run it through a pty so we mirror
            # the output live AND keep a bounded tail for failure reports. Any pty hiccup falls
            # back to a plain inherited-stdio run — reporting must never break an install.
            if not capture and not sudo and _can_tee():
                try:
                    rc, tail = _run_teed(argv, cwd, env, self.tee_limit)
                    return Result(full, rc, captured=tail)
                except Exception:               # noqa: BLE001 — degrade to plain streaming
                    pass
            cp = subprocess.run(argv, capture_output=capture, text=True,
                                cwd=cwd, env=env)
        return Result(full, cp.returncode,
                      stdout=cp.stdout if capture else '',
                      stderr=cp.stderr if capture else '')
