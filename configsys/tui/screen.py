'''screen.py — curses lifecycle helpers.

curses_screen(): initialize keypad/hidden-cursor mode and guarantee teardown.
suspended(): drop out of curses to run a child (apt) in the normal terminal, then resume — used
when the user executes staged operations mid-session.

We run cbreak (NOT raw), so Ctrl-C still raises KeyboardInterrupt and the context-manager teardown
restores the terminal even on SIGINT. On top of cbreak we turn OFF CR->NL folding (curses.nonl() +
clearing the tty's ICRNL), the way vim does, so the Return key (CR / KEY_ENTER) is DISTINCT from
Ctrl-J (LF, byte 10) — letting Ctrl-J/Ctrl-K serve as page-down/up without shadowing Enter. That
folding is re-enabled on teardown and momentarily handed back to a suspended child.

direct_color_term(): which terminfo entry to start curses with. Terminals advertise 24-bit color
via COLORTERM but almost all still say TERM=xterm-256color, and under that entry ncurses can only
fake truecolor by REDEFINING palette slots (OSC 4 via init_color). Terminals that ignore OSC 4
(e.g. COSMIC's terminal) then show the stock 256-cube at those slots — every color wrong. So when
the terminal claims truecolor we initialize against the matching `-direct` entry instead, where a
color number IS a packed RGB sent as a real 24-bit SGR (the Palette's `direct` path).
'''

import curses
import os
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


_TERMINFO_DIRS = ('/etc/terminfo', '/lib/terminfo', '/usr/share/terminfo', '/usr/lib/terminfo',
                  '/usr/local/share/terminfo', '/opt/homebrew/share/terminfo')


def _terminfo_exists(name, env):
    dirs = [env.get('TERMINFO'), os.path.expanduser('~/.terminfo')]
    dirs += (env.get('TERMINFO_DIRS') or '').split(':')
    dirs += _TERMINFO_DIRS
    for d in filter(None, dirs):
        for sub in (name[0], f'{ord(name[0]):x}'):          # Linux layout, then macOS hex layout
            if os.path.isfile(os.path.join(d, sub, name)):
                return True
    return False


def direct_color_term(env=None):
    '''The `-direct` terminfo name to initialize curses with, or None to keep $TERM. Only when the
    terminal claims truecolor (COLORTERM=truecolor|24bit, or an explicit --color 24bit), the color
    cap allows it, python's curses can address >256 colors, and a sibling `<base>-direct` entry is
    installed (xterm-256color -> xterm-direct, foot -> foot-direct). Not under tmux/screen, whose
    truecolor passthrough is its own configuration.'''
    from .theme import env_color_cap
    env = os.environ if env is None else env
    term = env.get('TERM') or ''
    cap = env_color_cap(env)
    colorterm = (env.get('COLORTERM') or '').strip().lower()
    if cap not in (None, 'truecolor') or (cap is None and colorterm not in ('truecolor', '24bit')):
        return None
    if not term or 'direct' in term or env.get('TMUX') or term.startswith(('screen', 'tmux')):
        return None
    try:
        if not curses.has_extended_color_support():
            return None
    except AttributeError:
        return None
    base = term[:-len('-256color')] if term.endswith('-256color') else term
    name = f'{base}-direct'
    return name if _terminfo_exists(name, env) else None


@contextmanager
def direct_color_env():
    '''Swap TERM to the `-direct` entry for curses initialization only (ncurses reads TERM once, at
    initscr), restoring it after, so children run from the TUI still see the user's real TERM.'''
    name = direct_color_term()
    old = os.environ.get('TERM')
    if name:
        os.environ['TERM'] = name
    try:
        yield
    finally:
        if name:
            os.environ['TERM'] = old


@contextmanager
def curses_screen():
    with direct_color_env():
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
