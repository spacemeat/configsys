'''base.py — the Screen protocol the MVVM TUI is built from (docs/d2-mvvm-plan.md).

A Screen owns its model (the existing state classes — MenuState, ProfileScreen, … — move in as-is)
and exposes three seams:

- `build_vm(ctx, size) -> ViewModel`: compute the frame's render model. PURE — reads the model and
  ctx, does no drawing. This is what makes a screen renderable headlessly and testable.
- `draw(surface, pal, vm)`: paint the ViewModel through a Surface. A dumb painter — it positions and
  colours, but decides nothing the ViewModel didn't already settle.
- `handle(key, host) -> Intent`: process one key. Mutates the model; asks the host (via the returned
  Intent, or host helpers for the things that must happen mid-key like modals) to switch screen, set
  the status note, mark the components tree dirty, execute a plan, or quit.

`build_vm`/`draw` are split from a single legacy `_draw_*` painter so the SUM paints identically —
the render-equivalence harness proves it — not reimagined. Over successive passes `draw` gets thinner
as more decision moves up into `build_vm`.
'''

from dataclasses import dataclass


class ViewModel:
    '''Base for a screen's render model: plain data, no curses, no ctx. A screen subclasses this with
    the fields its `draw` paints (header text, rows, cells, scroll offsets, legend). Kept trivial on
    purpose — the value is that it is INSPECTABLE and comparable, not that it enforces a schema.'''


@dataclass
class Size:
    '''The drawable area a build_vm lays out against (curses getmaxyx order: h then w).'''
    h: int
    w: int


@dataclass
class Intent:
    '''What a key press asks the router to do. Defaults mean "handled, nothing else": the model may
    have changed (cursor moved, selection toggled) with no router action needed. A screen sets fields
    to request cross-cutting effects the router owns.'''
    handled: bool = True        # False -> the key wasn't consumed here; let the router try globals
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

    def handle(self, key, host):
        raise NotImplementedError
