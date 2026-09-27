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
the terminal renders truecolor we initialize against the matching `-direct` entry instead (building
it with `tic` when the system lacks one), where a color number IS a packed RGB sent as a real
24-bit SGR (the Palette's `direct` path).
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


def _terminfo_exists(name, env, system=True):
    dirs = [env.get('TERMINFO')]
    if system:
        dirs += [os.path.expanduser('~/.terminfo')] + (env.get('TERMINFO_DIRS') or '').split(':')
        dirs += _TERMINFO_DIRS
    for d in filter(None, dirs):
        for sub in (name[0], f'{ord(name[0]):x}'):          # Linux layout, then macOS hex layout
            if os.path.isfile(os.path.join(d, sub, name)):
                return True
    return False


# The direct-color overlay (ncurses' own `xterm+direct` fragment), layered over the terminal's
# entry via `use=` when the system lacks a `-direct` entry: those ship in `ncurses-term`, which a
# fresh Debian/Ubuntu/Pop install does NOT have (only `ncurses-base`). Earlier caps win in terminfo,
# so these override the base's color caps; everything else (keys, etc.) comes from $TERM.
_DIRECT_OVERLAY = r'''%(name)s|%(term)s with direct color (built by configsys),
	RGB, colors#0x1000000, pairs#0x10000, CO#8, initc@, ccc@, setb@, setf@,
	op=\E[39;49m,
	setab=\E[%%?%%p1%%{8}%%<%%t4%%p1%%d%%e48:2::%%p1%%{65536}%%/%%d:%%p1%%{256}%%/%%{255}%%&%%d:%%p1%%{255}%%&%%d%%;m,
	setaf=\E[%%?%%p1%%{8}%%<%%t3%%p1%%d%%e38:2::%%p1%%{65536}%%/%%d:%%p1%%{256}%%/%%{255}%%&%%d:%%p1%%{255}%%&%%d%%;m,
	use=%(term)s,
'''


def _cache_terminfo_dir(env):
    base = env.get('XDG_CACHE_HOME') or os.path.join(os.path.expanduser('~'), '.cache')
    return os.path.join(base, 'configsys', 'terminfo')


def _build_direct_entry(name, term, env):
    '''Compile `name` = $TERM + the direct-color overlay into configsys' cache with `tic` (ncurses-bin,
    always present where ncurses is). Returns the terminfo dir holding it, or None if it can't be
    built (no tic, $TERM unknown to tic, unwritable cache). Reused once built.'''
    import shutil
    import subprocess
    out = _cache_terminfo_dir(env)
    if _terminfo_exists(name, {'TERMINFO': out}, system=False):
        return out
    tic = shutil.which('tic')
    if not tic:
        return None
    try:
        os.makedirs(out, exist_ok=True)
        src = os.path.join(out, f'{name}.src')
        with open(src, 'w') as f:
            f.write(_DIRECT_OVERLAY % {'name': name, 'term': term})
        # env passes through TERMINFO/TERMINFO_DIRS so `use=$TERM` resolves an entry the terminal
        # ships privately (kitty: TERMINFO -> its own xterm-kitty)
        r = subprocess.run([tic, '-x', '-o', out, src], capture_output=True, timeout=10, env=dict(env))
    except (OSError, subprocess.SubprocessError):
        return None
    return out if r.returncode == 0 and _terminfo_exists(name, {'TERMINFO': out}, system=False) else None


# TERM values whose terminal always renders 24-bit color. TERM (unlike COLORTERM) is forwarded
# over SSH, so these carry the signal to a remote configsys too.
_TRUECOLOR_TERMS = ('xterm-kitty', 'alacritty', 'foot', 'wezterm', 'xterm-ghostty', 'contour',
                    'rio', 'mintty', 'iterm2')
# TERM_PROGRAM / LC_TERMINAL (the latter forwarded over SSH by the default `SendEnv LC_*`)
_TRUECOLOR_PROGRAMS = ('iterm.app', 'iterm2', 'wezterm', 'vscode', 'ghostty', 'hyper', 'tabby')


def _truecolor_signal(env):
    '''Does anything in the environment say this terminal renders 24-bit color? COLORTERM is the
    convention; the rest cover the cases it's dropped (SSH doesn't forward it, sudo/su scrub it).'''
    if (env.get('COLORTERM') or '').strip().lower() in ('truecolor', '24bit'):
        return True
    term = (env.get('TERM') or '').lower()
    if term.startswith(_TRUECOLOR_TERMS):
        return True
    if any((env.get(k) or '').strip().lower() in _TRUECOLOR_PROGRAMS
           for k in ('TERM_PROGRAM', 'LC_TERMINAL')):
        return True
    if env.get('WT_SESSION') or env.get('KONSOLE_VERSION'):     # Windows Terminal, Konsole
        return True
    try:                                        # VTE (GNOME Terminal, Tilix, …): colon SGR since 0.52
        return int(env.get('VTE_VERSION') or 0) >= 5200
    except ValueError:
        return False


def direct_color_setup(env=None):
    '''(terminfo name, terminfo dir or None) to initialize curses with for direct 24-bit color, or
    None to keep $TERM. Only when the terminal renders truecolor (see _truecolor_signal, or an
    explicit --color 24bit), the color cap allows it, and python's curses can address >256 colors.
    Uses the system's sibling `<base>-direct` entry (xterm-256color -> xterm-direct) when installed,
    else builds one into the cache (dir returned). Inside tmux too — tmux itself downconverts RGB for
    an outer terminal that can't show it — but not GNU screen, which may not pass RGB at all.'''
    from .theme import env_color_cap
    env = os.environ if env is None else env
    term = env.get('TERM') or ''
    cap = env_color_cap(env)
    if cap not in (None, 'truecolor') or (cap is None and not _truecolor_signal(env)):
        return None
    if not term or 'direct' in term or (term.startswith('screen') and not env.get('TMUX')):
        return None
    try:
        if not curses.has_extended_color_support():
            return None
    except AttributeError:
        return None
    base = term[:-len('-256color')] if term.endswith('-256color') else term
    name = f'{base}-direct'
    if _terminfo_exists(name, env):
        return name, None
    built = _build_direct_entry(name, term, env)
    return (name, built) if built else None


def direct_color_term(env=None):
    '''Just the terminfo name direct_color_setup() would start curses with (None = keep $TERM).'''
    setup = direct_color_setup(env)
    return setup[0] if setup else None


@contextmanager
def direct_color_env():
    '''Swap TERM (and TERMINFO, for a cache-built entry) to the direct-color entry for curses
    initialization only (ncurses reads them once, at initscr), restoring them after, so children run
    from the TUI still see the user's real TERM.'''
    setup = direct_color_setup()
    saved = {k: os.environ.get(k) for k in ('TERM', 'TERMINFO')}
    if setup:
        os.environ['TERM'] = setup[0]
        if setup[1]:
            os.environ['TERMINFO'] = setup[1]
    try:
        yield
    finally:
        if setup:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


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
