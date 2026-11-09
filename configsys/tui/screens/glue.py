'''glue.py — the Glue screen as a Screen (build_vm/draw/handle).

The model is `panes.GlueScreen` (state + the glue driver ops), composed as `self.model`; this adds
the three MVVM seams (docs/tui-architecture.md):

- build_vm: computes the PURE render content — the per-row cells + column widths / virtual xs, the
  display list (per-shell group headers and rows) resolved to drawable form, each row's state->element
  role, and the status/nav strings. No curses, no geometry that needs the drawn borders.
- draw: lays the content out (panel rect, the shared table painter — screens/table.py — whose clamped
  scroll it records with vm.settle) and paints it — no decisions the VM didn't already settle.
- handle: one key, returning an Intent(note) for the router. Glue tracks mutated unit keys in the
  model's own `dirty` SET.
'''

from collections import Counter

from .. import menu
from ...drivers.glue import GLUE_STATE_LABEL as _GLUE_STATE_LABEL
from ..flows import _pretend_note
from ..paint import _fit, _page_rows, _panel, _put
from ..panes import _DF_STATE_ELEM, _GLUE_HEADERS, _glue_cells, _is_user_glue, GlueScreen as _GlueModel
from ..screen import suspended
from . import table
from .base import Intent, Screen, ViewModel, result_ok, results_note


class GlueVM(ViewModel):
    '''Pure render content for one Glue frame — settled by build_vm, painted by draw.'''

    def __init__(self):
        self.has_rows = False
        self.empty_header = ''     # the joined header line shown when there is nothing to list
        self.empty_msg = ''
        # table content (scroll-independent)
        self.cells = []            # list[list[str]] — 4 columns per row (indexed like model.rows)
        self.widths = []           # column widths
        self.xs = []               # column virtual-x starts
        self.virt_w = 0
        self.elems = []            # role name per row (the un-selected element)
        self.headers = _GLUE_HEADERS
        # the display list resolved to drawable form:
        #   ('hdr', '<shell>  loader: <label> ')  — a section rule (padded with ─ to the panel width)
        #   ('row', i)                            — a snippet row, i indexes cells/elems/model.rows
        self.display = []
        self.cur_disp = 0          # display index of the cursor row (0 if the cursor isn't listed)
        self.cur = 0               # the model's cursor (row index)
        # chrome
        self.status = ''
        self.note = ''             # transient action note (host-supplied)
        self.nav = ''


def _nav_str():
    g = lambda a: menu._keymap().glyph('glue', a)
    return (f" {g('down')}/{g('up')} · {g('left')}/{g('right')} scroll · {g('activate')} activate · "
            f"{g('activate-group')} activate group · {g('deactivate')} deactivate · "
            f"{g('new-snippet')} new · {g('override')} override · {g('staged')} staged · {g('quit')} ")


class GlueScreen(Screen):
    id = 'glue'

    def __init__(self, ctx, model=None):
        self.ctx = ctx
        self.model = model if model is not None else _GlueModel(ctx)

    def reload(self):
        self.model.reload()

    # -- build_vm ---------------------------------------------------------

    def build_vm(self, ctx, size):
        gs = self.model
        vm = GlueVM()
        vm.cur = gs.cur
        vm.has_rows = bool(gs.display)
        if not gs.display:
            vm.empty_header = '   '.join(_GLUE_HEADERS)
            vm.empty_msg = '(no installed shells / no glue in the install set)'
        else:
            vm.cells = [_glue_cells(r) for r in gs.rows]
            vm.widths, vm.xs, vm.virt_w = table.layout(_GLUE_HEADERS, vm.cells)
            vm.elems = [_DF_STATE_ELEM.get(r[3], 'component') for r in gs.rows]
            for entry in gs.display:
                if entry[0] == 'hdr':            # a per-shell section header + its loader status
                    _, shell, lstate = entry
                    lbl = (_GLUE_STATE_LABEL.get(lstate, lstate) if lstate else 'not wired')
                    vm.display.append(('hdr', f'{shell}  loader: {lbl} '))
                else:
                    vm.display.append(('row', entry[1]))
            vm.cur_disp = next((d for d, e in enumerate(gs.display) if e == ('row', gs.cur)), 0)
        # tallied by the STATE column's own label (active / changed / available / inactive), as the
        # Glue ? page and `dotfiles status` count them — available is not lumped in with inactive
        n = Counter(_glue_cells(r)[1] for r in gs.rows)
        status = f' {len(gs.rows)} glue snippet(s)   {n["active"]} active'
        if n['changed']:
            status += f'   {n["changed"]} changed ({menu._keymap().glyph("glue", "activate-group")} to re-activate)'
        for label in ('available', 'inactive'):
            if n[label]:
                status += f'   {n[label]} {label}'
        n_user = sum(1 for r in gs.rows if _is_user_glue(r))
        if n_user:
            status += f'   ({n_user} your own user glue)'
        vm.status = status
        vm.nav = _nav_str()
        return vm

    # -- draw -------------------------------------------------------------

    def draw(self, surface, pal, vm):
        gs = self.model
        h, w = self.begin_page(surface, pal)
        it, il, ih, iw = _panel(surface, pal, 1, 0, h - 3, w, 'glue (shell integration)', True, h, w)
        if not vm.has_rows:
            _put(surface, it, il, _fit(vm.empty_header, iw), pal.style('menu_header', it, il, h, w))
            _put(surface, it + 1, il, _fit(vm.empty_msg, iw), pal.style('info_dim', it + 1, il, h, w))
        else:
            top, hscroll, page_h = table.draw_table(surface, pal, (it, il, ih, iw), vm, vm.cur,
                                            gs.top, gs.hscroll, h, w)
            vm.settle(top=top, hscroll=hscroll, page_h=page_h)

        self.end_page(surface, pal, vm.status + (f'    {vm.note}' if vm.note else ''), [vm.nav], h, w)

    # -- handle -----------------------------------------------------------

    def handle(self, ch, ctx, stdscr, pal):
        '''One key. Mutates the model (cursor/scroll, and `model.dirty` — the SET of unit keys an
        activate/deactivate touched), runs glue driver ops under `suspended`, returns an Intent(note).'''
        gs = self.model
        row = gs.cur_row()          # (rc, comp, tgt, state, src, shell)
        km = menu._keymap()
        gact = km.action_for('glue', ch)
        note = None
        try:
            if gact in menu._NAV_ACTIONS:
                gs.cur = menu.ListNav.apply(gact, gs.cur, len(gs.rows) - 1, lambda: _page_rows(stdscr, getattr(gs, 'page_h', None)))
            elif gact == 'left':                      # horizontal scroll across the columns
                gs.hscroll = max(0, gs.hscroll - 4)
            elif gact == 'right':
                gs.hscroll += 4
            elif gact == 'activate' and row and _is_user_glue(row):   # USER glue: (re)link the
                with suspended(stdscr):                 # shell's user.d namespace into conf.d
                    gs.gd.deploy_user_glue(row[5])
                gs.reload()
                note = f'linked your user glue for {row[5]} ({row[1]})'
            elif gact == 'deactivate' and row and _is_user_glue(row):   # not a unit -> nothing to unlink
                note = (f'{row[1]} is your own glue: configsys links every user.d snippet and never '
                        f'edits it — delete or move {row[4]} to stop it loading')
            elif gact == 'activate' and row:        # activate the current snippet for ITS shell only
                with suspended(stdscr):
                    res = gs.gd.install(row[0], only_shells=[row[5]])
                gs.dirty.add(row[0].key)
                gs.reload()
                note = (f'{row[0].comp}: {res.output.strip()}' if res is not None and not res.ok
                        else _pretend_note(ctx, f'activated {row[0].comp} ({row[5]})', True))
            elif gact == 'deactivate' and row:      # deactivate this shell's link (leaves conf.d + content)
                with suspended(stdscr):
                    res = gs.gd.uninstall(row[0], only_shells=[row[5]])
                gs.dirty.add(row[0].key)
                gs.reload()
                ok, why = result_ok(res)
                note = _pretend_note(ctx, f'deactivated {row[0].comp} ({row[5]})' if ok
                                     else f'{row[0].comp}: {why or "deactivate failed"}', ok)
            elif gact == 'activate-group' and row:  # (re)activate EVERY snippet in THIS shell's group
                shell = row[5]
                # re-install the whole group, not just the inactive rows: glue install is
                # idempotent and drift-refreshes, so this also picks up an active-but-stale
                # store copy after the shipped snippet changed (the gestalt/inline case).
                grp = {r[0].key: r[0] for r in gs.rows if r[5] == shell and not _is_user_glue(r)}
                user = [r for r in gs.rows if r[5] == shell and _is_user_glue(r)]
                n_inactive = sum(1 for r in gs.rows
                                 if r[5] == shell and r[3] not in ('linked', 'loader-on'))
                results = []
                with suspended(stdscr):
                    for rc in grp.values():                      # scope to THIS shell, not the component's others
                        # link only: the shell is hooked up ONCE below — an inline (nu/elvish) block
                        # rebuilt per snippet re-ran every #!cs-eval generator N times
                        results.append((rc.comp, *result_ok(gs.gd.install(rc, only_shells=[shell],
                                                                          hookup=False))))
                    hooked = gs.gd.deploy_user_glue(shell)       # the loader + the shell's user.d snippets
                    if user:
                        results.append(('your user glue', *result_ok(hooked)))
                    for w in (getattr(gs.gd, 'hookup_warnings', None) or []) + \
                            (getattr(gs.gd, 'inline_warnings', None) or []):
                        results.append(('the loader', False, w))
                gs.dirty.update(grp)
                gs.reload()
                note = results_note(ctx, '(re)activated', results, what='snippet(s)',
                                    tail=f' in the {shell} group ({n_inactive} newly active)',
                                    nothing=f'no snippets in the {shell} group')
            elif gact == 'new-snippet':           # `glue add` for this row's shell (CLI parity, G4)
                import argparse
                from ...cli.dotfiles import cmd_glue_add
                name = menu._input_box(stdscr, pal, 'new snippet — name', '')
                if name and name.strip():
                    with suspended(stdscr):
                        rc_ = cmd_glue_add(ctx, argparse.Namespace(name=name.strip(), local=False,
                                                                   shell=row[5] if row else None))
                    gs.reload()
                    note = f'added your snippet {name.strip()}' if rc_ == 0 else f'{name.strip()}: not added'
            elif gact == 'override' and row and not _is_user_glue(row):
                import argparse
                from ...cli.dotfiles import cmd_glue_override
                with suspended(stdscr):
                    rc_ = cmd_glue_override(ctx, argparse.Namespace(comp=row[0].comp, shell=row[5], local=False))
                gs.reload()
                note = f'{row[0].comp}: overridden ({row[5]})' if rc_ == 0 else f'{row[0].comp}: not overridden'
            elif gact == 'staged':                # the shell-writes guard's captures: activate / discard
                from ... import shellguard
                staged = shellguard.list_staged(ctx.paths)
                if not staged:
                    note = 'nothing staged — no installer has tried to write your rc files'
                else:
                    opts = [(f'{comp} ({shell})', '') for comp, shell, _p in staged]
                    i = menu._popup_choose(stdscr, pal, 'staged installer writes', opts, 0)
                    if i is not None:
                        comp, shell, path = staged[i]
                        what = menu._popup_choose(stdscr, pal, f'{comp} ({shell}) — {path.name}',
                                                  [('activate as your own glue', ''), ('discard it', ''),
                                                   ('leave it staged', '')], 2)
                        if ctx.runner.pretend and what in (0, 1):
                            note = f'[pretend] would {"activate" if what == 0 else "discard"} {comp}'
                        elif what == 0:
                            done = shellguard.activate(ctx.paths, comp, ctx.runner)
                            gs.reload()
                            note = f'{comp}: activated as your glue ({len(done)} shell(s))'
                        elif what == 1:
                            note = f'{comp}: discarded {shellguard.discard(ctx.paths, comp)} block(s)'
        except Exception as e:  # noqa: BLE001 — surface, don't crash
            note = f'error: {e}'
        return Intent(note=note)
