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

    # -- the page chrome every draw shares (review-2026-11-2 D7 / tui-screens-09) --

    def begin_page(self, surface, pal):
        '''Clear `surface` and paint the chrome every page opens with — this page's palette, the
        gradient background, the row-0 screen chips. -> (h, w).'''
        from ..menu import _draw_nav, _fill_bg
        surface.erase()
        h, w = surface.getmaxyx()
        pal.use_page(self.id)
        if pal.gradient:
            _fill_bg(surface, pal, h, w)
        _draw_nav(surface, pal, self.id, h, w)
        return h, w

    def end_page(self, surface, pal, status, legends, h, w):
        '''Close a page: the `status` row (skipped when None) directly above the bottom `legends`
        rows, then refresh.'''
        from ..menu import _fit, _put
        y = h - len(legends)
        if status is not None:
            _put(surface, y - 1, 0, _fit(status, w), pal.style('status_line', y - 1, 0, h, w))
        for k, text in enumerate(legends):
            _put(surface, y + k, 0, _fit(text.ljust(w), w), pal.style('footer', y + k, 0, h, w))
        surface.refresh()


def results_note(ctx, did, results, *, what='', tail='', nothing='nothing to do'):
    """The status note for a BULK action, built from what happened — never the intent (B16 /
    tui-screens-05): `did` the past-tense verb phrase ("activated", "unmanaged"), `results` a list of
    (name, ok, why). "activated 5 of 6 — fd-glue failed: …", and under --pretend a "would" note."""
    if not results:
        return nothing
    ok = [n for n, good, _w in results if good]
    bad = [(n, w) for n, good, w in results if not good]
    head = (f'{did} {len(ok)}' + (f' of {len(results)}' if bad else '')
            + (f' {what}' if what else '') + tail)
    if bad:
        name, why = bad[0]
        head += f' — {name} failed' + (f': {why}' if why else '') + (f' (+{len(bad) - 1} more)'
                                                                      if len(bad) > 1 else '')
    if getattr(getattr(ctx, 'runner', None), 'pretend', False):
        return f'[pretend] nothing changed — would have: {head}'
    return head


def result_ok(res):
    """(ok, why) of a driver Result or a plain bool (None = nothing to report: ok)."""
    if res is None or isinstance(res, bool):
        return (res is not False), ''
    out = (getattr(res, 'output', '') or '').strip().splitlines()
    return bool(getattr(res, 'ok', True)), (out[-1] if out else '')

