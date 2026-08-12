'''runner.py — the single subprocess chokepoint for the whole app.

Every shell-out goes through Runner.run so that:
  * --pretend/dry-run can print commands instead of executing them (safe on the
    host, and makes command construction assertable in tests),
  * the terminal can be released cleanly when shelling out from inside the curses
    TUI (so sudo/apt can prompt and paint normally),
  * tests can inject a recording/mock runner.
'''

import fcntl
import os
import select
import signal
import subprocess
import sys
import termios
import threading
import tty
from contextlib import contextmanager


def _pty_ctty():
    '''A/B toggle for the streamed-build terminal strategy. Default (unset): pre-authenticate sudo
    (presudo) so a build's internal sudo doesn't prompt inside the tee. Set CONFIGSYS_PTY_CTTY=1: give
    the teed child its OWN controlling terminal (the pty), so an internal prompt flows through the tee
    naturally — the holistic fix that makes presudo unnecessary. Env-gated so the two can be compared
    on a real build before the workaround is retired.'''
    return bool(os.environ.get('CONFIGSYS_PTY_CTTY'))


def _child_setctty():
    '''preexec_fn: runs in the child AFTER start_new_session's setsid() (so it's a session leader with
    no controlling terminal) and AFTER stdin/out/err are dup'd onto the pty slave (so fd 0 IS the
    slave). Claim that slave as the controlling terminal: then the child's `/dev/tty` is the pty, so
    an internal `sudo` reads the password FROM the pty (relayed by the tee loop — no dual-reader
    contention) and a forwarded Ctrl-C reaches this session's foreground group. Kept minimal (module
    globals only, no import/alloc) since it runs post-fork; a failure raises -> Popen raises ->
    _run_teed degrades to plain streaming (where sudo prompts un-teed anyway).'''
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


@contextmanager
def terminal_released(tui_active: bool):
    '''Temporarily hand the terminal back to a child process. When the TUI is
    active, leave the alternate screen / restore sane modes first, then restore
    them afterward. A no-op (beyond SIGINT forwarding) when no TUI is running.

    Off the MAIN thread this is a complete no-op: the only caller there is the
    background startup-inspection worker running captured, read-only probes, which
    never own the tty. Touching it there — termios save/restore, SIGINT swap, the
    alt-screen escapes — races the main thread's curses setup and can drop the TUI
    back into cooked/echo mode (keys echo, need Enter). signal.signal() would also
    raise off the main thread. So a background child gets the terminal untouched.'''
    if threading.current_thread() is not threading.main_thread():
        yield
        return

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

    # While the child owns the terminal, the PARENT must not die on Ctrl+C (it's the TUI/CLI). Use a
    # no-op HANDLER, not SIG_IGN: a caught signal is reset to SIG_DFL in the child across exec, so the
    # child (cmake, make, …) receives Ctrl+C and stops — whereas SIG_IGN is INHERITED across exec, so
    # the child would ignore Ctrl+C too (a long source build you couldn't interrupt). Both keep the
    # parent alive; only the handler lets the child be interrupted.
    old_int = signal.signal(signal.SIGINT, lambda *_: None)
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

    def __init__(self, cmd, returncode, stdout='', stderr='', pretended=False, captured='',
                 advisory=False):
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout or ''
        self.stderr = stderr or ''
        self.pretended = pretended
        self.captured = captured or ''   # tee'd tail of streamed output (capture=False builds)
        # advisory: a non-ok result that is EXPECTED and user-actionable (e.g. dotfiles refusing to
        # overwrite un-adopted config), NOT a bug — the app explains it instead of offering `report`.
        self.advisory = advisory

    @property
    def ok(self):
        return self.returncode == 0

    @property
    def output(self):
        '''The best available command output: captured stdout/stderr, else the tee'd tail.'''
        return (self.stdout + self.stderr).strip() or self.captured.strip()

    @classmethod
    def fail(cls, reason, returncode=1):
        '''A pre-flight failure with NO command run: the reason rides in stderr so it flows to
        the TUI summary (_fail_detail) and the report's Driver output — instead of being stuffed
        into `cmd`, where neither looks. `cmd` stays empty so the report shows no spurious
        Command block.'''
        return cls('', returncode, stderr=reason)


def _can_tee():
    '''True when we can run a streamed child through a pty and mirror its output: needs a
    real controlling terminal on both ends (tests/pipes fall back to plain streaming).'''
    if not hasattr(os, 'openpty'):
        return False
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _run_teed(argv, cwd, env, limit, ctty=False):
    '''Run argv with its stdio on a pty: stream output to the real terminal live while
    retaining the last `limit` bytes, and forward the user's keystrokes to the child (so an
    interactive build still works). Returns (returncode, captured_tail). The child sees a tty,
    so colour/progress behave as normal.

    `ctty=True` gives the child its OWN session with the pty slave as its controlling terminal
    (start_new_session + TIOCSCTTY via _child_setctty). Then a `sudo` (or any prompt) the child runs
    INTERNALLY reads from the pty — relayed by this loop — instead of racing us on the real /dev/tty,
    and a forwarded Ctrl-C reaches the child's foreground group. Without it (the historical default),
    the child shares our real controlling terminal, so an internal sudo prompt would deadlock (see
    Runner._preauth_sudo). master is always closed; a Popen/preexec failure propagates so the caller
    degrades to plain streaming.'''
    import pty
    master, slave = pty.openpty()
    try:
        try:                                    # match the child pty to the real window size
            sz = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b'\0' * 8)
            fcntl.ioctl(master, termios.TIOCSWINSZ, sz)
        except Exception:                       # noqa: BLE001 — best effort
            pass
        popen_kw = dict(stdin=slave, stdout=slave, stderr=slave, cwd=cwd, env=env, close_fds=True)
        if ctty:                                # the child owns the pty as its controlling terminal
            popen_kw.update(start_new_session=True, preexec_fn=_child_setctty)
        try:
            proc = subprocess.Popen(argv, **popen_kw)
        finally:
            os.close(slave)
        in_fd = sys.stdin.fileno()
        old = None
        try:
            old = termios.tcgetattr(in_fd)
            tty.setraw(in_fd)                   # child pty owns echo/line-editing -> single echo
        except Exception:                       # noqa: BLE001
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
                    except OSError:             # EIO on Linux once the child exits == EOF
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
                except Exception:               # noqa: BLE001
                    pass
        text = tail.decode('utf-8', 'replace').replace('\r\n', '\n')   # de-pty the line endings
        return proc.wait(), text
    finally:
        os.close(master)


def _sudo_keepalive():
    '''Refresh the sudo timestamp non-interactively every ~60s until the returned Event is set — so a
    long teed build (~40 min) whose internal sudo runs past the ~15 min sudo timeout never has to
    RE-prompt mid-build (a prompt inside the tee deadlocks: the tee loop and sudo both read the one
    terminal). Daemon thread; `-n` + DEVNULL stdio so it never prompts, blocks, or touches the tty.'''
    stop = threading.Event()

    def loop():
        while not stop.wait(60):
            try:
                subprocess.run(['sudo', '-n', '-v'], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:            # noqa: BLE001 — best-effort; never crash the build
                pass
    threading.Thread(target=loop, daemon=True).start()
    return stop


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

    def _preauth_sudo(self):
        '''Prompt for the sudo password ONCE, un-teed, on the inherited terminal — so a following
        teed build that runs `sudo` internally (to install system deps) finds a valid timestamp and
        never prompts. A prompt INSIDE the tee deadlocks: `_run_teed` holds the real stdin in raw mode
        and reads it to feed the pty, while sudo reads the same /dev/tty for the password — two readers
        on one terminal, so keystrokes are split and sudo hangs (and raw mode swallows Ctrl-C). Doing
        it here, before the tee starts, keeps the prompt on a normal terminal. Best-effort: a declined
        auth just means the build may prompt itself (still un-teed via the plain fallback).'''
        self.calls.append('sudo bash -c true')
        self.echo('configsys: this build may need sudo (system deps) — authenticating now so it '
                  "won't stop to prompt mid-build.")
        try:
            subprocess.run(['sudo', 'bash', '-c', 'true'])   # inherits the tty -> a normal prompt
        except Exception:                # noqa: BLE001 — never let pre-auth break the run
            pass

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None,
            cwd=None, env=None, presudo=False) -> Result:
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
                # presudo: the command sudo's internally (a source build installing deps). Two
                # strategies (A/B via CONFIGSYS_PTY_CTTY): default = pre-auth un-teed + keep the
                # timestamp warm so the internal sudo never prompts inside the tee; ctty = give the
                # child the pty as its controlling terminal so the prompt flows through the tee
                # naturally (then presudo is unnecessary). Only meaningful on the teed path.
                ctty = _pty_ctty()
                keepalive = None
                if presudo and not ctty:
                    self._preauth_sudo()
                    keepalive = _sudo_keepalive()
                try:
                    rc, tail = _run_teed(argv, cwd, env, self.tee_limit, ctty=ctty)
                    return Result(full, rc, captured=tail)
                except Exception:               # noqa: BLE001 — degrade to plain streaming
                    pass
                finally:
                    if keepalive is not None:
                        keepalive.set()
            # A CAPTURED run is a read-only probe (get_version, installed_index, …) that never needs
            # input — and the background inspection worker fires these while curses owns the terminal.
            # Inheriting stdin (the real tty) lets such a child reset the terminal's modes and drop
            # the TUI back into cooked/echo (keys echo, need Enter). Detach stdin so a probe child can
            # NEVER touch the controlling terminal; a STREAMED (capture=False) op keeps the tty (sudo
            # password, interactive build) and is fenced by terminal_released on the main thread.
            cp = subprocess.run(argv, capture_output=capture, text=True, cwd=cwd, env=env,
                                stdin=(subprocess.DEVNULL if capture else None))
        return Result(full, cp.returncode,
                      stdout=cp.stdout if capture else '',
                      stderr=cp.stderr if capture else '')
