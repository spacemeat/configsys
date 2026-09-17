'''screen.py — curses lifecycle helpers.

curses_screen(): initialize keypad/hidden-cursor mode and guarantee teardown.
suspended(): drop out of curses to run a child (apt) in the normal terminal, then resume — used
when the user executes staged operations mid-session.

We run cbreak (NOT raw), so Ctrl-C still raises KeyboardInterrupt and the context-manager teardown
restores the terminal even on SIGINT. On top of cbreak we turn OFF CR->NL folding (curses.nonl() +
clearing the tty's ICRNL), the way vim does, so the Return key (CR / KEY_ENTER) is DISTINCT from
Ctrl-J (LF, byte 10) — letting Ctrl-J/Ctrl-K serve as page-down/up without shadowing Enter. That
folding is re-enabled on teardown and momentarily handed back to a suspended child.
'''

import curses
import signal
import sys
from contextlib import contextmanager

try:
    import termios
except ImportError:                          # non-POSIX (Windows) — curses.nonl() alone
    termios = None


def distinct_return_mode():
    '''Make Return (CR / KEY_ENTER) distinct from Ctrl-J (LF): stop curses + the tty folding CR->NL.
    Keeps cbreak's signals (ISIG) so Ctrl-C still interrupts. Idempotent — also re-applied when
    resuming from a suspended child.'''
    curses.nonl()
    if termios is not None:
        try:
            fd = sys.stdin.fileno()
            attrs = termios.tcgetattr(fd)
            attrs[0] &= ~termios.ICRNL        # iflag: do not map CR -> NL on input
            termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
        except (termios.error, ValueError, OSError):
            pass                              # not a tty (pipe/test) — nonl() is the best we can do


def _restore_cr_nl():
    '''Re-enable CR->NL folding for the shell (endwin usually does this; belt-and-suspenders so the
    terminal is never left with Return "broken" — even after a SIGINT-driven teardown).'''
    curses.nl()
    if termios is not None:
        try:
            fd = sys.stdin.fileno()
            attrs = termios.tcgetattr(fd)
            attrs[0] |= termios.ICRNL
            termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
        except (termios.error, ValueError, OSError):
            pass


@contextmanager
def curses_screen():
    stdscr = curses.initscr()
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)
    distinct_return_mode()                    # CR != LF (see module docstring)
    try:
        # cbreak keeps ISIG, so Ctrl-C raises SIGINT — but a blocking getch() would restart through
        # it (SA_RESTART) and hang. Let SIGINT interrupt the read, so KeyboardInterrupt propagates and
        # the teardown below restores the terminal even on Ctrl-C.
        signal.siginterrupt(signal.SIGINT, True)
    except (ValueError, OSError):
        pass
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    try:
        yield stdscr
    finally:
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        curses.nocbreak()
        stdscr.keypad(False)
        curses.echo()
        curses.endwin()
        _restore_cr_nl()                      # hand the shell back a normal Return


@contextmanager
def suspended(stdscr):
    '''Temporarily leave curses so a child process owns the real terminal in NORMAL (CR->NL) mode.'''
    curses.def_prog_mode()                    # remember our program mode (CR!=LF)
    curses.endwin()
    _restore_cr_nl()                          # the child sees a normal terminal
    try:
        yield
    finally:
        curses.reset_prog_mode()              # back to our program mode...
        distinct_return_mode()                # ...and re-assert CR != LF
        stdscr.refresh()
        curses.doupdate()
