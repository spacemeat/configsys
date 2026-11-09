'''configsys.tui.screens — one module per TUI screen, each a Screen (build_vm/draw/handle).

`base` holds the Screen protocol + ViewModel + Intent (docs/tui-architecture.md); each screen module
holds its ViewModel, build_vm, draw and handle, composing a state model from tui/models.py (Components),
panes.py or preview.py; `table` is the table painter Plugins / Glue / Dotfiles share.
'''

from .base import Intent, Screen, ViewModel

__all__ = ['Screen', 'ViewModel', 'Intent']
