'''glue.py — the Glue screen as a Screen (build_vm/draw/handle).

Second screen migrated off the monolithic menu.py painter (docs/d2-mvvm-plan.md), mirroring
screens/plugins.py. The model is the existing `menu.GlueScreen` (state + the glue driver ops),
composed unchanged; this adds the three MVVM seams:

- build_vm: computes the PURE render content — the per-row cells + column widths / virtual xs, the
  display list (per-shell group headers and rows) resolved to drawable form, each row's state->element
  role, and the status/nav strings. No curses, no geometry that needs the drawn borders.
- draw: lays the content out (panel rect, scroll clamps written back to the model, scrollbars via the
  shared widgets) and paints it — no decisions the VM didn't already settle. It reproduces
  menu._draw_glue cell for cell, which test_screen_glue pins against the legacy painter.
- handle: the former `if screen == 'glue'` dispatch, returning an Intent(note) instead of mutating
  loop-scope locals. Glue tracks mutated unit keys in the model's own `dirty` SET.
'''

from .. import menu
from ..menu import (_DF_STATE_ELEM, _GLUE_HEADERS, _GLUE_STATE_LABEL, GlueScreen as _GlueModel,
                    _draw_nav, _fill_bg, _fit, _page_rows, _panel, _glue_cells, _put, _put_hscroll,
                    _scroll_top, _scrollbar_h, _scrollbar_v)
from ..screen import suspended
from .base import Intent, Screen, ViewModel


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
    km = menu._KEYMAP
    if km is not None:
        g = lambda a: km.glyph('glue', a)
        return (f" {g('down')}/{g('up')} · {g('left')}/{g('right')} scroll · {g('activate')} activate · "
                f"{g('activate-group')} activate group · {g('deactivate')} deactivate · {g('quit')} ")
    return ' j/k · h/l scroll · a activate · A activate group · x deactivate · q '


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
            vm.widths = [max(len(_GLUE_HEADERS[c]), max((len(cs[c]) for cs in vm.cells), default=0))
                         for c in range(len(_GLUE_HEADERS))]
            vx = 0
            for wd in vm.widths:
                vm.xs.append(vx)
                vx += wd + 2
            vm.virt_w = vx - 2
            vm.elems = [_DF_STATE_ELEM.get(r[3], 'component') for r in gs.rows]
            for entry in gs.display:
                if entry[0] == 'hdr':            # a per-shell section header + its loader status
                    _, shell, lstate = entry
                    lbl = (_GLUE_STATE_LABEL.get(lstate, lstate) if lstate else 'not wired')
                    vm.display.append(('hdr', f'{shell}  loader: {lbl} '))
                else:
                    vm.display.append(('row', entry[1]))
            vm.cur_disp = next((d for d, e in enumerate(gs.display) if e == ('row', gs.cur)), 0)
        n_active = sum(1 for r in gs.rows if r[3] in ('linked', 'loader-on'))
        n_changed = sum(1 for r in gs.rows if r[3] == 'drifted')
        n_inactive = len(gs.rows) - n_active - n_changed
        status = f' {len(gs.rows)} glue snippet(s)   {n_active} active'
        if n_changed:
            status += f'   {n_changed} changed (A to re-activate)'
        status += f'   {n_inactive} inactive'
        vm.status = status
        vm.nav = _nav_str()
        return vm

    # -- draw -------------------------------------------------------------

    def draw(self, surface, pal, vm):
        gs = self.model
        surface.erase()
        h, w = surface.getmaxyx()
        pal.use_page('glue')
        if pal.gradient:
            _fill_bg(surface, pal, h, w)
        _draw_nav(surface, pal, 'glue', h, w)
        it, il, ih, iw = _panel(surface, pal, 1, 0, h - 3, w, 'glue (shell integration)', True, h, w)
        if not vm.has_rows:
            _put(surface, it, il, _fit(vm.empty_header, iw), pal.style('menu_header', it, il, h, w))
            _put(surface, it + 1, il, _fit(vm.empty_msg, iw), pal.style('info_dim', it + 1, il, h, w))
        else:
            has_hbar = vm.virt_w > iw
            rows_h = ih - 1 - (1 if has_hbar else 0)
            gs.hscroll = max(0, min(gs.hscroll, max(0, vm.virt_w - iw)))
            for hdr, vx0 in zip(vm.headers, vm.xs):
                _put_hscroll(surface, it, il, iw, vx0, gs.hscroll, hdr,
                             pal.style('menu_header', it, il, h, w))
            disp = vm.display
            gs.top = _scroll_top(vm.cur_disp, gs.top, rows_h, len(disp))
            for vis, d in enumerate(range(gs.top, min(len(disp), gs.top + rows_h))):
                y = it + 1 + vis
                entry = disp[d]
                if entry[0] == 'hdr':
                    rule = entry[1]
                    rule += '─' * max(0, iw - len(rule))
                    _put(surface, y, il, _fit(rule, iw), pal.style('menu_header', y, il, h, w))
                    continue
                i, sel = entry[1], entry[1] == vm.cur
                if sel:
                    _put(surface, y, il, ' ' * iw, pal.fill(y, il, h, w, selected=True))
                elem = 'label' if sel else vm.elems[i]
                style = pal.style(elem, y, il, h, w, selected=sel)
                for cell, wd, vx0 in zip(vm.cells[i], vm.widths, vm.xs):
                    _put_hscroll(surface, y, il, iw, vx0, gs.hscroll, cell.ljust(wd), style)
            _scrollbar_v(surface, pal, it + 1, il + iw, rows_h, gs.top, rows_h, len(disp), h, w)
            if has_hbar:
                _scrollbar_h(surface, pal, it + ih - 1, il, iw, gs.hscroll, iw, vm.virt_w, h, w)

        _put(surface, h - 2, 0, _fit(vm.status + (f'    {vm.note}' if vm.note else ''), w),
             pal.style('status_line', h - 2, 0, h, w))
        _put(surface, h - 1, 0, _fit(vm.nav.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
        surface.refresh()

    # -- handle -----------------------------------------------------------

    def handle(self, ch, ctx, stdscr, pal):
        '''One key. Mutates the model (cursor/scroll, and `model.dirty` — the SET of unit keys an
        activate/deactivate touched), runs glue driver ops under `suspended`, returns an Intent(note).
        Ported verbatim from the former glue dispatch.'''
        gs = self.model
        row = gs.cur_row()          # (rc, comp, tgt, state, src, shell)
        km = menu._KEYMAP
        gact = km.action_for('glue', ch) if km is not None else None
        note = None
        try:
            if gact == 'down':
                gs.cur = min(len(gs.rows) - 1, gs.cur + 1)
            elif gact == 'up':
                gs.cur = max(0, gs.cur - 1)
            elif gact == 'page-down':
                gs.cur = min(len(gs.rows) - 1, gs.cur + _page_rows(stdscr))
            elif gact == 'page-up':
                gs.cur = max(0, gs.cur - _page_rows(stdscr))
            elif gact == 'left':                      # horizontal scroll across the columns
                gs.hscroll = max(0, gs.hscroll - 4)
            elif gact == 'right':
                gs.hscroll += 4
            elif gact == 'top':
                gs.cur = 0
            elif gact == 'bottom':
                gs.cur = max(0, len(gs.rows) - 1)
            elif gact == 'activate' and row:        # activate the current snippet for ITS shell only
                with suspended(stdscr):
                    res = gs.gd.install(row[0], only_shells=[row[5]])
                gs.dirty.add(row[0].key)
                gs.reload()
                note = (f'{row[0].comp}: {res.output.strip()}' if res is not None and not res.ok
                        else f'activated {row[0].comp} ({row[5]})')
            elif gact == 'deactivate' and row:      # deactivate this shell's link (leaves conf.d + content)
                with suspended(stdscr):
                    gs.gd.uninstall(row[0], only_shells=[row[5]])
                gs.dirty.add(row[0].key)
                gs.reload()
                note = f'deactivated {row[0].comp} ({row[5]})'
            elif gact == 'activate-group' and row:  # (re)activate EVERY snippet in THIS shell's group
                shell = row[5]
                # re-install the whole group, not just the inactive rows: glue install is
                # idempotent and drift-refreshes, so this also picks up an active-but-stale
                # store copy after the shipped snippet changed (the gestalt/inline case).
                grp = {r[0].key: r[0] for r in gs.rows if r[5] == shell}
                n_inactive = sum(1 for r in gs.rows
                                 if r[5] == shell and r[3] not in ('linked', 'loader-on'))
                with suspended(stdscr):
                    for rc in grp.values():
                        gs.gd.install(rc, only_shells=[shell])   # scope to THIS shell, not the component's others
                gs.dirty.update(grp)
                gs.reload()
                note = (f'(re)activated {len(grp)} snippet(s) in the {shell} group'
                        f' ({n_inactive} newly active)' if grp
                        else f'no snippets in the {shell} group')
        except Exception as e:  # noqa: BLE001 — surface, don't crash
            note = f'error: {e}'
        return Intent(note=note)
