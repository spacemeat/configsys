'''configsys.tui — interactive curses front-end.

`run(ctx)` (menu.run, the router) is the entry the app calls for the default (no-subcommand)
invocation. Each screen is a `Screen` (screens/: build_vm / draw / handle) over a state model
(models.MenuState for Components; panes / preview for the rest), painting through a Surface
(docs/tui-architecture.md).
'''

from .menu import run

__all__ = ['run']
