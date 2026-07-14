import os, signal, subprocess, sys, termios
from contextlib import contextmanager

@contextmanager
def terminal_released(tui_active: bool):
    fd = sys.stdin.fileno()
    isatty = os.isatty(fd)
    saved = termios.tcgetattr(fd) if isatty else None

    if tui_active:
        sys.stdout.write(
                "\x1b[?1049l"                       # leave alternate screen
                "\x1b[?25h"                         # show cursor
                "\x1b[?0m"                          # reset SGR
                "\x1b[?7h"                          # re-enable line wrap
                "\x1b[?1000l\x1b[?1002l\x1b[?1006l" # mouse reporting off
                "\x1b[?2004l"                       # bracketed paste off
                )
        sys.stdout.flush()

    # propagate Ctrl-C to child
    old_int = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, old_int)
        if isatty:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        if tui_active:
            sys.stdout.write("\x1b[?1049h") # TODO: correct position?
            sys.stdout.flush()

def shellCmd(cmd: str, *, tui_active: bool = False, cwd=None, env=None) -> subprocess.CompletedProcess:
    with terminal_released(tui_active):
        return subprocess.run(["bash", "-c", cmd], cwd=cwd, env=env)

