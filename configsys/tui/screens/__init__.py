'''configsys.tui.screens — one module per TUI screen, each a Screen (build_vm/draw/handle).

The MVVM split of the former monolithic menu.py (docs/d2-mvvm-plan.md). `base` holds the Screen
protocol + ViewModel; each screen module holds its model, its ViewModel, and its painter.
'''

from .base import Intent, Screen, Size, ViewModel

__all__ = ['Screen', 'ViewModel', 'Intent', 'Size']
