'''configsys.tui — interactive curses front-end.

`run(ctx)` is the entry the app calls for the default (no-subcommand) invocation.
The stageable interaction logic lives in MenuState (pure, unit-tested); the curses
rendering/loop is a thin view over it.
'''

from .menu import run

__all__ = ['run']
