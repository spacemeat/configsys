'''dotfiles.py — the Dotfiles screen as a Screen (build_vm/draw/handle).

Migrated off the monolithic menu.py painter (docs/d2-mvvm-plan.md), mirroring the Plugins
pattern-setter. The model is the existing `menu.DotfilesScreen` (link-state table over the
via:dotfiles CONFIG units + the driver ops), composed unchanged; this adds the three MVVM seams:

- build_vm: computes the PURE render content — the per-row cells, column widths / virtual x starts,
  the display list, the per-row state element, the status (counts + at-risk clause) and nav strings.
  No curses, no panel geometry.
- draw: lays the content out (panel rect, scroll clamps, scrollbars via the shared widgets) and paints
  it. Reproduces menu._draw_dotfiles cell for cell, which test_screen_dotfiles pins against the legacy
  painter.
- handle: the former `if screen == 'dotfiles'` dispatch, returning an Intent(note) instead of
  mutating loop-scope locals.
'''

from pathlib import Path

from ...drivers.dotfiles import config_display_state
from .. import menu
from ..menu import (_DF_HEADERS, _DF_STATE_ELEM, DotfilesScreen as _DotfilesModel, _df_cells,
                    _draw_nav, _fill_bg, _fit, _page_rows, _panel, _popup_choose, _put,
                    _put_hscroll, _scroll_top, _scrollbar_h, _scrollbar_v)
from ..screen import suspended
from .base import Intent, Screen, ViewModel


class DotfilesVM(ViewModel):
    '''Pure render content for one Dotfiles frame — settled by build_vm, painted by draw.'''

    def __init__(self):
        self.has_rows = False
        self.empty_msg = ''
        self.headers = _DF_HEADERS
        # table content (scroll-independent)
        self.cells = []            # list[list[str]] — 4 columns per row
        self.widths = []           # column widths
        self.xs = []               # column virtual-x starts (two-space gutters)
        self.virt_w = 0
        self.elems = []            # role name per row (unselected)
        self.display = []          # ('hdr', label) | ('row', idx) — the scrolled list
        # chrome
        self.status = ''
        self.note = ''             # transient action note (host-supplied)
        self.nav = ''


def _nav_str():
    km = menu._KEYMAP
    if km is not None:
        g = lambda a: km.glyph('dotfiles', a)
        return (f" {g('manage')}/{g('manage-all')} manage · {g('unmanage')}/{g('unmanage-all')} unmanage · "
                f"{g('move-store')}/{g('move-store-all')} move store · {g('quit')} ")
    return ' m/M manage · u/U unmanage · s/S move store · h/l scroll · q '


class DotfilesScreen(Screen):
    id = 'dotfiles'

    def __init__(self, ctx, model=None):
        self.ctx = ctx
        self.model = model if model is not None else _DotfilesModel(ctx)

    def reload(self):
        self.model.reload()

    # -- build_vm ---------------------------------------------------------

    def build_vm(self, ctx, size):
        ds = self.model
        vm = DotfilesVM()
        vm.has_rows = bool(ds.rows)
        if not ds.rows:
            vm.empty_msg = '(no dotfiles in the active profiles)'
        else:
            # one cell-set per row; each column is sized to its longest cell so nothing is truncated —
            # horizontal scroll (h/l) reaches anything wider than the panel.
            vm.cells = [_df_cells(r) for r in ds.rows]
            vm.widths = [max(len(_DF_HEADERS[c]), max((len(cs[c]) for cs in vm.cells), default=0))
                         for c in range(len(_DF_HEADERS))]
            vx = 0
            for wd in vm.widths:
                vm.xs.append(vx)
                vx += wd + 2                     # two spaces between columns for breathing room
            vm.virt_w = vx - 2
            vm.elems = [_DF_STATE_ELEM.get(config_display_state(r[3], r[5]), 'component')
                        for r in ds.rows]
            vm.display = list(ds.display)
        counts = {}
        for r in ds.rows:
            s = config_display_state(r[3], r[5])
            counts[s] = counts.get(s, 0) + 1
        n_risk = sum(1 for r in ds.rows if r[3] == 'unmanaged')          # a real file we don't manage
        status = (f' {len(ds.rows)} config target(s)   '
                  + '   '.join(f'{counts[s]} {s}' for s in ('managed', 'unmanaged', 'no config')
                               if counts.get(s)))
        if n_risk:
            status += f'   ! {n_risk} unmanaged file(s) at risk — capture (c) before linking'
        vm.status = status
        vm.nav = _nav_str()
        return vm

    # -- draw -------------------------------------------------------------

    def draw(self, surface, pal, vm):
        ds = self.model
        surface.erase()
        h, w = surface.getmaxyx()
        pal.use_page('dotfiles')
        if pal.gradient:
            _fill_bg(surface, pal, h, w)
        _draw_nav(surface, pal, 'dotfiles', h, w)
        it, il, ih, iw = _panel(surface, pal, 1, 0, h - 3, w, 'dotfiles (config state)', True, h, w)
        if not vm.has_rows:
            _put(surface, it, il, _fit('   '.join(vm.headers), iw), pal.style('menu_header', it, il, h, w))
            _put(surface, it + 1, il, _fit(vm.empty_msg, iw), pal.style('info_dim', it + 1, il, h, w))
        else:
            has_hbar = vm.virt_w > iw
            rows_h = ih - 1 - (1 if has_hbar else 0)
            ds.hscroll = max(0, min(ds.hscroll, max(0, vm.virt_w - iw)))   # clamp: no scrolling past the end
            for hdr, vx0 in zip(vm.headers, vm.xs):    # sticky header, scrolls horizontally with the rows
                _put_hscroll(surface, it, il, iw, vx0, ds.hscroll, hdr, pal.style('menu_header', it, il, h, w))
            # scroll over the DISPLAY list (group headers + rows); the cursor tracks the actionable row.
            disp = vm.display
            cur_disp = next((d for d, e in enumerate(disp) if e == ('row', ds.cur)), 0)
            ds.top = _scroll_top(cur_disp, ds.top, rows_h, len(disp))
            for vis, d in enumerate(range(ds.top, min(len(disp), ds.top + rows_h))):
                y = it + 1 + vis
                etype, val = disp[d]
                if etype == 'hdr':                   # a group divider (drawn inline, non-selectable)
                    rule = f'{val} '
                    rule += '─' * max(0, iw - len(rule))
                    _put(surface, y, il, _fit(rule, iw), pal.style('menu_header', y, il, h, w))
                    continue
                i, sel = val, val == ds.cur
                if sel:
                    _put(surface, y, il, ' ' * iw, pal.fill(y, il, h, w, selected=True))
                elem = 'label' if sel else vm.elems[i]
                style = pal.style(elem, y, il, h, w, selected=sel)
                for cell, wd, vx0 in zip(vm.cells[i], vm.widths, vm.xs):
                    _put_hscroll(surface, y, il, iw, vx0, ds.hscroll, cell.ljust(wd), style)
            _scrollbar_v(surface, pal, it + 1, il + iw, rows_h, ds.top, rows_h, len(disp), h, w)
            if has_hbar:
                _scrollbar_h(surface, pal, it + ih - 1, il, iw, ds.hscroll, iw, vm.virt_w, h, w)

        _put(surface, h - 2, 0, _fit(vm.status + (f'    {vm.note}' if vm.note else ''), w),
             pal.style('status_line', h - 2, 0, h, w))
        _put(surface, h - 1, 0, _fit(vm.nav.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
        surface.refresh()

    # -- handle -----------------------------------------------------------

    def handle(self, ch, ctx, stdscr, pal):
        '''One key. Mutates the model (cursor/scroll, `dirty` unit keys), runs the dotfiles driver ops
        (under `suspended` where they own the terminal), returns an Intent(note). Ported verbatim from
        the former dotfiles dispatch.'''
        ds = self.model
        row = ds.cur_row()          # (rc, name, target, state, source, capturable)
        km = menu._KEYMAP
        dact = km.action_for('dotfiles', ch) if km is not None else None
        note = None
        try:
            if dact == 'down':
                ds.cur = min(len(ds.rows) - 1, ds.cur + 1)
            elif dact == 'up':
                ds.cur = max(0, ds.cur - 1)
            elif dact == 'page-down':
                ds.cur = min(len(ds.rows) - 1, ds.cur + _page_rows(stdscr))
            elif dact == 'page-up':
                ds.cur = max(0, ds.cur - _page_rows(stdscr))
            elif dact == 'left':                      # horizontal scroll across the columns
                ds.hscroll = max(0, ds.hscroll - 4)
            elif dact == 'right':
                ds.hscroll += 4                       # clamped to the content width in draw
            elif dact == 'top':
                ds.cur = 0
            elif dact == 'bottom':
                ds.cur = max(0, len(ds.rows) - 1)
            elif dact in ('manage', 'confirm') and row:   # MANAGE: adopt any on-system file, then
                drv = ds.driver_for(row[0])                # link (capture + link are ONE step)
                with suspended(stdscr):
                    drv.capture(row[0], force=False)   # no-op if nothing on-system to adopt
                    res = drv.install(row[0])          # links; backs up a pre-existing real file
                ds.dirty.add(row[0].key)
                ds.reload()
                note = (f'{row[0].comp}: {res.output.strip()}'
                        if res is not None and not res.ok else f'managing {row[0].comp}')
            elif dact == 'manage-all':              # capture + link every not-yet-managed config
                pend = {r[0].key: r[0] for r in ds.rows
                        if config_display_state(r[3], r[5]) == 'unmanaged'}
                with suspended(stdscr):
                    for rc in pend.values():
                        drv = ds.driver_for(rc)
                        drv.capture(rc, force=False)
                        drv.install(rc)
                ds.dirty.update(pend)
                ds.reload()
                note = (f'managing {len(pend)} config(s)' if pend else 'nothing to manage')
            elif dact == 'unmanage' and row:        # UNMANAGE: unlink (confirms first)
                if _popup_choose(stdscr, pal, f'unmanage {row[0].comp}?  (unlinks it; your '
                                 f'content stays in your store)',
                                 [('cancel', ''), ('unmanage', '')], 0) == 1:
                    with suspended(stdscr):
                        ds.driver_for(row[0]).uninstall(row[0])
                    ds.dirty.add(row[0].key)
                    ds.reload()
                    note = f'unmanaged {row[0].comp}'
            elif dact == 'unmanage-all':            # unlink every MANAGED config (confirms first)
                managed = {r[0].key: r[0] for r in ds.rows
                           if config_display_state(r[3], r[5]) == 'managed'}
                if not managed:
                    note = 'nothing managed to unmanage'
                elif _popup_choose(stdscr, pal, f'unmanage all {len(managed)} managed config(s)?  '
                                   f'(unlinks each; content stays in your store)',
                                   [('cancel', ''), ('unmanage all', '')], 0) == 1:
                    with suspended(stdscr):
                        for rc in managed.values():
                            ds.driver_for(rc).uninstall(rc)
                    ds.dirty.update(managed)
                    ds.reload()
                    note = f'unmanaged {len(managed)} config(s)'
            elif dact == 'move-store' and row:      # move this config to the OTHER store
                plug = ctx.paths.primary_dotfiles_dir
                if plug is None:
                    note = 'no primary plugin configured — nothing to move between'
                else:
                    to_plugin = not str(row[4]).startswith('<plugin>')   # source col shows where it lives
                    target = Path(plug) if to_plugin else ctx.paths.user_dotfiles_dir
                    with suspended(stdscr):
                        moved = ds.driver_for(row[0]).relocate(row[0], target)
                    ds.dirty.add(row[0].key)
                    ds.reload()
                    where = 'plugin (travels)' if to_plugin else 'local (this box)'
                    note = (f'moved {row[0].comp} to {where}' if moved
                            else f'nothing to move for {row[0].comp}')
            elif dact == 'move-store-all':          # chooser: move ALL configs to a store
                plug = ctx.paths.primary_dotfiles_dir
                if plug is None:
                    note = 'no primary plugin configured — nothing to move between'
                else:
                    # NB: `choice`, not `ch` — the legacy code rebound the key variable here.
                    choice = _popup_choose(stdscr, pal, 'move ALL configs to which store?',
                                           [('primary plugin (travels to your machines)', ''),
                                            ('local (this box only)', ''), ('cancel', '')], 0)
                    if choice in (0, 1):
                        target = Path(plug) if choice == 0 else ctx.paths.user_dotfiles_dir
                        n = 0
                        with suspended(stdscr):
                            for rc in ds.units:
                                if ds.driver_for(rc).relocate(rc, target):
                                    n += 1
                        ds.dirty.update(rc.key for rc in ds.units)
                        ds.reload()
                        note = f'moved {n} config(s) to {"plugin" if choice == 0 else "local"}'
        except Exception as e:  # noqa: BLE001 — surface, don't crash
            note = f'error: {e}'
        return Intent(note=note)
