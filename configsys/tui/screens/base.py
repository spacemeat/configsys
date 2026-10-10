'''base.py — the Screen protocol the MVVM TUI is built from (docs/tui-architecture.md).

A Screen owns its model (the state classes — MenuState, ProfileScreen, … — composed as `self.model`)
and exposes three seams:

- `build_vm(ctx, size) -> ViewModel`: compute the frame's render model. PURE — reads the model and
  ctx, does no drawing. `size` is the `(h, w)` tuple from `getmaxyx()`. This is what makes a screen
  renderable headlessly and testable.
- `draw(surface, pal, vm)`: paint the ViewModel through a Surface. A dumb painter — it positions and
  colours, but decides nothing the ViewModel and model didn't already settle.
- `handle(ch, ctx, stdscr, pal) -> Intent`: process one key (Components' takes `cfg, ledger` too —
  it re-runs the load pipeline). Mutates the model and may run modal loops inline on `stdscr`
  (popups, input boxes, the suspended confirm/execute prompt); asks the router, via the returned
  Intent, for the effects it owns — switch screen, set the status note, mark the Components tree
  dirty, adopt a re-probed state, open the `where` overlay.

The router (menu.run) resolves its own keys (quit/issues/help/screen switch — after the screen's own
key scope, see keyspec.Keymap.own_action) before calling `handle`, so every key that reaches
`handle` is the screen's to consume.
'''

from dataclasses import dataclass


class ViewModel:
    '''Base for a screen's render model: plain data, no curses, no ctx. A screen subclasses this with
    the fields its `draw` paints (header text, rows, cells, scroll offsets, legend). Kept trivial on
    purpose — the value is that it is INSPECTABLE and comparable, not that it enforces a schema.'''


@dataclass
class Intent:
    '''What a key press asks the router to do. Defaults mean "nothing else": the model may
    have changed (cursor moved, selection toggled) with no router action needed. A screen sets fields
    to request cross-cutting effects the router owns.'''
    goto: str = None            # switch to this screen id
    note: str = None            # status-line note to show next frame
    dirty: bool = False         # the Components tree must be rebuilt (a pick/route/config edit)
    quit: bool = False          # leave the TUI
    new_pal: object = None      # a rebuilt Palette to adopt (Theme live-preview edits re-instantiate it)
    open_where: object = None   # (lines, subject) -> open the full-page `where` overlay
    pending_notes: object = None  # messages to surface AFTER the TUI exits (deferred install hints)
    # Components-specific: a pin/execute/refresh re-probes and rebinds the shared inspection state.
    reloaded: object = None     # (ms, cfg, ledger, states, diags) from a _reload — the router adopts it
    remodeled: object = None    # (ms, states, layouts, transitive) from a view-MODE switch
    pending_report: object = None      # a failed op's component key, for the post-quit report nudge
    invalidate_ps_overlay: bool = False  # an execute changed disk reality -> Profiles must re-enumerate


class Screen:
    '''One TUI screen. Subclasses set `id` (the router key AND the keymap scope) and implement the
    three seams. The model lives on the instance; the router keeps one Screen per id for the session.'''

    id = ''

    def build_vm(self, ctx, size):
        raise NotImplementedError

    def draw(self, surface, pal, vm):
        raise NotImplementedError

    def handle(self, ch, ctx, stdscr, pal):
        raise NotImplementedError
