'''screen.py — curses lifecycle helpers.

curses_screen(): initialize raw/keypad/hidden-cursor mode and guarantee teardown.
suspended(): drop out of curses to run a child (apt) in the normal terminal, then
resume — used when the user executes staged operations mid-session.
'''

import curses
from contextlib import contextmanager


@contextmanager
def curses_screen():
    stdscr = curses.initscr()
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)
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


@contextmanager
def suspended(stdscr):
    '''Temporarily leave curses so a child process owns the real terminal.'''
    curses.def_prog_mode()
    curses.endwin()
    try:
        yield
    finally:
        stdscr.refresh()
        curses.doupdate()
