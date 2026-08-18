'''runner.py — the single subprocess chokepoint for the whole app.

Every shell-out goes through Runner.run so that:
  * --pretend/dry-run can print commands instead of executing them (safe on the
    host, and makes command construction assertable in tests),
  * the terminal can be released cleanly when shelling out from inside the curses
    TUI (so sudo/apt can prompt and paint normally),
  * tests can inject a recording/mock runner.
'''

import collections
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


def _child_setctty():
    '''preexec_fn: runs in the child AFTER start_new_session's setsid() (so it's a session leader with
    no controlling terminal) and AFTER stdin/out/err are dup'd onto the pty slave (so fd 0 IS the
    slave). Claim that slave as the controlling terminal: then the child's `/dev/tty` is the pty, so
    an internal `sudo` reads the password FROM the pty (relayed by the tee loop — no dual-reader
    contention) and a forwarded Ctrl-C reaches this session's foreground group. Kept minimal (module
    globals only, no import/alloc) since it runs post-fork; a failure raises -> Popen raises ->
    _run_teed degrades to plain streaming (where sudo prompts un-teed anyway).'''
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


# A sane terminal: leave alt-screen, show cursor, reset SGR, wrap on, mouse + bracketed-paste off.
_SANE_TERM = ('\x1b[?1049l\x1b[?25h\x1b[0m\x1b[?7h\x1b[?1000l\x1b[?1002l\x1b[?1006l\x1b[?2004l')

# Terminal restoration on FATAL exit. _run_teed puts the real terminal in raw mode (and a child may
# change its modes); those are undone in `finally` on a normal/exception exit. But SIGTERM/SIGHUP
# terminate the process WITHOUT running finally, leaving the terminal wedged (raw, no echo — you'd need
# `reset`). These guards re-run the restoration on a fatal signal or at interpreter exit. (SIGKILL is
# uncatchable — nothing to do there; both real fixes above just remove the reason to send one.)
_TERM_GUARDS = []            # stack of zero-arg restore callables, run on SIGTERM/SIGHUP/atexit
_TERM_HOOKS = False


def _run_term_guards(*_a):
    while _TERM_GUARDS:
        try:
            _TERM_GUARDS.pop()()
        except Exception:    # noqa: BLE001 — a dying process must not raise out of cleanup
            pass


def _install_term_hooks():
    global _TERM_HOOKS
    if _TERM_HOOKS:
        return
    _TERM_HOOKS = True
    import atexit
    atexit.register(_run_term_guards)
    for sig in (signal.SIGTERM, signal.SIGHUP):
        prev = signal.getsignal(sig)

        def handler(signum, frame, sig=sig, prev=prev):
            _run_term_guards()                     # un-wreck the terminal first
            # restore the prior disposition and re-raise, so the process still dies as it would have
            signal.signal(sig, prev if (prev in (signal.SIG_DFL, signal.SIG_IGN) or callable(prev))
                          else signal.SIG_DFL)
            os.kill(os.getpid(), sig)
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):              # signal unavailable / not main thread
            pass


@contextmanager
def _term_guard(restore):
    '''Register `restore` to also run on SIGTERM/SIGHUP/atexit while active — a fatal signal bypasses
    the local `finally`, so this is what un-wedges the terminal then. Main-thread only (signal.signal
    raises off-main; only the main thread ever owns the tty). Deregistered on normal unwind, so it
    never double-restores or fires after a clean exit.'''
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    _install_term_hooks()
    _TERM_GUARDS.append(restore)
    try:
        yield
    finally:
        try:
            _TERM_GUARDS.remove(restore)
        except ValueError:
            pass


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
        sys.stdout.write(_SANE_TERM)
        sys.stdout.flush()

    # On a FATAL signal (SIGTERM/SIGHUP) or interpreter exit, the `finally` below never runs — so
    # register the same restoration to run then, un-wedging a terminal left in raw mode by a teed
    # child. (We're already out of the alt-screen here, so this restores termios + reasserts sane
    # modes and stops there — it never re-enters the alt-screen of a dying process.)
    def _restore_on_fatal():
        if tui_active:
            try:
                sys.stdout.write(_SANE_TERM)
                sys.stdout.flush()
            except Exception:    # noqa: BLE001
                pass
        if isatty and saved is not None:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, saved)
            except Exception:    # noqa: BLE001
                pass

    # While the child owns the terminal, the PARENT must not die on Ctrl+C (it's the TUI/CLI). Use a
    # no-op HANDLER, not SIG_IGN: a caught signal is reset to SIG_DFL in the child across exec, so the
    # child (cmake, make, …) receives Ctrl+C and stops — whereas SIG_IGN is INHERITED across exec, so
    # the child would ignore Ctrl+C too (a long source build you couldn't interrupt). Both keep the
    # parent alive; only the handler lets the child be interrupted.
    old_int = signal.signal(signal.SIGINT, lambda *_: None)
    with _term_guard(_restore_on_fatal):
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


def _run_teed(argv, cwd, env, limit):
    '''Run argv with its stdio on a pty: stream output to the real terminal live while
    retaining the last `limit` bytes, and forward the user's keystrokes to the child (so an
    interactive build still works). Returns (returncode, captured_tail). The child sees a tty,
    so colour/progress behave as normal.

    The child gets its OWN session with the pty slave as its controlling terminal (start_new_session +
    TIOCSCTTY via _child_setctty). So a `sudo` (or any prompt) the child runs INTERNALLY reads from
    the pty — relayed by this loop — instead of racing us on the real /dev/tty, and a forwarded Ctrl-C
    reaches the child's foreground group. master is always closed; a Popen/preexec failure propagates
    so the caller degrades to plain streaming (where an internal sudo prompts un-teed anyway).'''
    import pty
    master, slave = pty.openpty()
    try:
        try:                                    # match the child pty to the real window size
            sz = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b'\0' * 8)
            fcntl.ioctl(master, termios.TIOCSWINSZ, sz)
        except Exception:                       # noqa: BLE001 — best effort
            pass
        try:                                    # the child owns the pty as its controlling terminal
            proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, cwd=cwd, env=env,
                                    close_fds=True, start_new_session=True, preexec_fn=_child_setctty)
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


def _run_captured_tty(argv, cwd, env, limit):
    '''Run argv keeping the REAL controlling terminal as stdin, while capturing stdout+stderr through
    a pipe that we mirror live to the terminal and keep a bounded tail of. Returns (rc, tail).

    Unlike _run_teed (which gives the child a fresh pty), the child keeps OUR tty on stdin — so a
    `sudo` here finds the credential we pre-cached on that same tty (tty_tickets keys the timestamp by
    tty, so a pty'd op would be a different tty and re-prompt every time) and, as a last resort, could
    still prompt on it. Used for top-level `sudo=True` ops. Progress/colour degrade to plain (stdout
    is a pipe, not a tty), which is the acceptable cost of not re-prompting on every op.'''
    proc = subprocess.Popen(argv, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            cwd=cwd, env=env, text=True, bufsize=1)
    tail = collections.deque(maxlen=max(1, limit // 80))   # ~limit bytes, counted in lines
    # terminal_released holds a NO-OP SIGINT handler so the parent survives Ctrl-C during a single
    # interactive build. For a batch install we want the opposite: Ctrl-C should abort the WHOLE run,
    # not just kill this op and march on. So restore the normal handler for the duration — Ctrl-C then
    # raises KeyboardInterrupt HERE (the child, in our process group, gets the SIGINT too and dies); we
    # reap it and re-raise so the install loop can stop. (Best effort off the main thread.)
    try:
        old = signal.signal(signal.SIGINT, signal.default_int_handler)
    except (ValueError, OSError):
        old = None
    try:
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            tail.append(line)
        return proc.wait(), ''.join(tail)
    except KeyboardInterrupt:
        try:
            proc.wait(timeout=5)               # child is dying from the same Ctrl-C — reap it
        except Exception:                      # noqa: BLE001
            proc.kill()
        raise                                  # propagate -> the batch loop aborts
    finally:
        try:
            proc.stdout.close()
        except Exception:                      # noqa: BLE001
            pass
        if old is not None:
            try:
                signal.signal(signal.SIGINT, old)
            except (ValueError, OSError):
                pass


def _sudo_preauth():
    '''Cache the sudo credential ONCE on the real terminal (one prompt if a password is needed),
    so a subsequently-teed `sudo` op won't have to prompt mid-stream — which is what lets us
    capture sudo-install output without the pty/password contention that used to wedge the
    terminal. Returns True iff sudo is now usable non-interactively. Best-effort (never raises).'''
    try:
        subprocess.run(['sudo', '-v'])                    # inherits the tty; prompts once if needed
        cp = subprocess.run(['sudo', '-n', '-v'], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return cp.returncode == 0
    except Exception:                                     # noqa: BLE001
        return False


class _SudoKeepalive:
    '''Refresh the cached sudo credential every 50s (well under the default 15-min timeout) until
    stop(), so a long teed op (a big install / source build with spaced-out sudo calls) never has
    the credential expire and re-prompt mid-stream. Daemon thread; best-effort.'''
    def __init__(self):
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def _loop(self):
        while not self._stop.wait(50):
            try:
                subprocess.run(['sudo', '-n', '-v'], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:                             # noqa: BLE001
                return

    def stop(self):
        self._stop.set()


class Runner:
    def __init__(self, pretend=False, echo=None):
        self.pretend = pretend
        self._echo = echo
        self.tui_active = False  # set by the app while the curses TUI owns the screen
        self.calls = []  # every full command string, in order (for tests/logs)
        self.tee_limit = 64 * 1024  # bytes of streamed output retained for failure reports
        self._sudo_warm = False       # sudo credential pre-cached for this batch (real tty)
        self._keepalive = None        # _SudoKeepalive refreshing it, for the batch's duration

    def echo(self, msg):
        if self._echo:
            self._echo(msg)

    # -- sudo session: one prompt per batch, kept warm --------------------

    def _ensure_sudo(self):
        '''Warm the sudo credential ONCE for this batch — one prompt on the real terminal if a
        password is needed — and keep it refreshed, so every subsequent sudo op reuses the SAME
        real-tty ticket without re-prompting. This is the fix for tty_tickets (per-tty credential
        caching): pre-auth on the real tty + run sudo ops on that same tty. Returns True iff sudo is
        usable non-interactively now. Best-effort; never raises.'''
        if self._sudo_warm:
            return True
        if _sudo_preauth():
            self._sudo_warm = True
            if self._keepalive is None:
                self._keepalive = _SudoKeepalive()
            return True
        return False

    def end_sudo(self):
        '''Drop the keepalive + warm flag at the end of a batch, so sudo can lapse to its normal
        timeout afterwards (we don't hold the machine authenticated indefinitely).'''
        if self._keepalive is not None:
            self._keepalive.stop()
            self._keepalive = None
        self._sudo_warm = False

    @contextmanager
    def sudo_session(self):
        '''Scope a batch of ops: sudo is pre-authed lazily on the first privileged op and kept warm,
        then released here. Wrap a multi-component install/upgrade so it prompts at most once.'''
        try:
            yield
        finally:
            self.end_sudo()

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None,
            cwd=None, env=None, presudo=False) -> Result:
        # `presudo=True` (source builds whose script calls sudo internally): pre-authenticate sudo +
        # keep-alive around the teed run, so the build's internal sudo doesn't stall waiting for a
        # password it can't prompt for cleanly. A top-level `sudo=True` op pre-auths too (below).
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
            # Streamed op on a real terminal: run it through a pty so we mirror the output live AND
            # keep a bounded tail for failure reports. For a PRIVILEGED op (`sudo=True`) — or a build
            # whose internal sudo needs the tty (`presudo`) — pre-authenticate sudo ONCE here and keep
            # the credential warm, so the teed command never prompts mid-stream; that's what lets us
            # capture sudo-install output cleanly (the teed sudo then behaves like the already-working
            # non-sudo tee). Any pty hiccup or a failed pre-auth degrades to a plain inherited-stdio
            # run — reporting must never break an install.
            if not capture and _can_tee():
                if sudo:
                    # Top-level privileged op: warm the credential ONCE for the batch, then run on the
                    # REAL tty (capturing stdout via a pipe) so the pre-authed ticket applies. A pty'd
                    # op (the tee path) would be a DIFFERENT tty and, under tty_tickets, re-prompt on
                    # every op — the cascade the user hits. Falls back to plain streaming if pre-auth
                    # fails (couldn't cache creds -> it may prompt per-op, but nothing wedges).
                    if self._ensure_sudo():
                        try:
                            rc, tail = _run_captured_tty(argv, cwd, env, self.tee_limit)
                            return Result(full, rc, captured=tail)
                        except Exception:       # noqa: BLE001 — degrade to plain streaming
                            pass
                else:
                    # A non-sudo streamed op, or a build whose script runs sudo INTERNALLY (`presudo`),
                    # which needs a pty to prompt into — pre-auth (best effort) then tee.
                    if presudo:
                        self._ensure_sudo()
                    try:
                        rc, tail = _run_teed(argv, cwd, env, self.tee_limit)
                        return Result(full, rc, captured=tail)
                    except Exception:           # noqa: BLE001 — degrade to plain streaming
                        pass
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
