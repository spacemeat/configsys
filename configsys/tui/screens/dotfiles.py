'''dotfiles.py — the Dotfiles screen as a Screen (build_vm/draw/handle).

Migrated off the monolithic menu.py painter (docs/done/d2-mvvm-plan.md), mirroring the Plugins
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
from ...errors import ConfigError
from .. import menu
from ..modals import _popup_choose
from ..paint import _fit, _page_rows, _panel, _put
from ..panes import _df_cells, _DF_HEADERS, _DF_STATE_ELEM, DotfilesScreen as _DotfilesModel
from ..flows import _pretend_note
from ..screen import suspended
from . import table
from .base import Intent, Screen, ViewModel, result_ok, results_note


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
    g = lambda a: menu._keymap().glyph('dotfiles', a)
    return (f" {g('manage')}/{g('manage-all')} manage · {g('unmanage')}/{g('unmanage-all')} unmanage · "
            f"{g('move-store')}/{g('move-store-all')} move store · {g('quit')} ")


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
            vm.widths, vm.xs, vm.virt_w = table.layout(_DF_HEADERS, vm.cells)
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
        h, w = self.begin_page(surface, pal)
        it, il, ih, iw = _panel(surface, pal, 1, 0, h - 3, w, 'dotfiles (config state)', True, h, w)
        if not vm.has_rows:
            _put(surface, it, il, _fit('   '.join(vm.headers), iw), pal.style('menu_header', it, il, h, w))
            _put(surface, it + 1, il, _fit(vm.empty_msg, iw), pal.style('info_dim', it + 1, il, h, w))
        else:
            top, hscroll = table.draw_table(surface, pal, (it, il, ih, iw), vm, ds.cur,
                                            ds.top, ds.hscroll, h, w)
            vm.settle(top=top, hscroll=hscroll)

        self.end_page(surface, pal, vm.status + (f'    {vm.note}' if vm.note else ''), [vm.nav], h, w)

    # -- handle -----------------------------------------------------------

    def handle(self, ch, ctx, stdscr, pal):
        '''One key. Mutates the model (cursor/scroll, `dirty` unit keys), runs the dotfiles driver ops
        (under `suspended` where they own the terminal), returns an Intent(note). Ported verbatim from
        the former dotfiles dispatch.'''
        ds = self.model
        row = ds.cur_row()          # (rc, name, target, state, source, capturable)
        km = menu._keymap()
        dact = km.action_for('dotfiles', ch)
        note = None
        try:
            if dact in menu._NAV_ACTIONS:
                ds.cur = menu.ListNav.apply(dact, ds.cur, len(ds.rows) - 1, lambda: _page_rows(stdscr))
            elif dact == 'left':                      # horizontal scroll across the columns
                ds.hscroll = max(0, ds.hscroll - 4)
            elif dact == 'right':
                ds.hscroll += 4                       # clamped to the content width in draw
            elif dact in ('manage', 'confirm') and row:   # MANAGE: adopt any on-system file, then
                drv = ds.driver_for(row[0])                # link (capture + link are ONE step)
                with suspended(stdscr):
                    drv.capture(row[0], force=False)   # no-op if nothing on-system to adopt
                    res = drv.install(row[0])          # links; backs up a pre-existing real file
                ds.dirty.add(row[0].key)
                ds.reload()
                note = (f'{row[0].comp}: {res.output.strip()}'
                        if res is not None and not res.ok
                        else _pretend_note(ctx, f'managing {row[0].comp}', True))
            elif dact == 'manage-all':              # capture + link every not-yet-managed config
                pend = {r[0].key: r[0] for r in ds.rows
                        if config_display_state(r[3], r[5]) == 'unmanaged'}
                results = []
                with suspended(stdscr):
                    for rc in pend.values():
                        drv = ds.driver_for(rc)
                        try:                          # one bad manifest.hu must not stop the rest
                            drv.capture(rc, force=False)
                            results.append((rc.comp, *result_ok(drv.install(rc))))
                        except (ConfigError, RuntimeError) as e:
                            results.append((rc.comp, False, str(e)))
                ds.dirty.update(pend)
                ds.reload()
                note = results_note(ctx, 'now managing', results, what='config(s)', nothing='nothing to manage')
            elif dact == 'unmanage' and row:        # UNMANAGE: unlink (confirms first)
                if _popup_choose(stdscr, pal, f'unmanage {row[0].comp}?  (unlinks it; your '
                                 f'content stays in your store)',
                                 [('cancel', ''), ('unmanage', '')], 0) == 1:
                    with suspended(stdscr):
                        ok, why = result_ok(ds.driver_for(row[0]).uninstall(row[0]))
                    ds.dirty.add(row[0].key)
                    ds.reload()
                    note = _pretend_note(ctx, f'unmanaged {row[0].comp}' if ok
                                         else f'{row[0].comp}: {why or "unmanage failed"}', ok)
            elif dact == 'unmanage-all':            # unlink every MANAGED config (confirms first)
                managed = {r[0].key: r[0] for r in ds.rows
                           if config_display_state(r[3], r[5]) == 'managed'}
                if not managed:
                    note = 'nothing managed to unmanage'
                elif _popup_choose(stdscr, pal, f'unmanage all {len(managed)} managed config(s)?  '
                                   f'(unlinks each; content stays in your store)',
                                   [('cancel', ''), ('unmanage all', '')], 0) == 1:
                    results = []
                    with suspended(stdscr):
                        for rc in managed.values():
                            results.append((rc.comp, *result_ok(ds.driver_for(rc).uninstall(rc))))
                    ds.dirty.update(managed)
                    ds.reload()
                    note = results_note(ctx, 'unmanaged', results, what='config(s)')
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
                    note = _pretend_note(ctx, f'moved {row[0].comp} to {where}' if moved
                                         else f'nothing to move for {row[0].comp}', bool(moved))
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
                        note = _pretend_note(ctx, f'moved {n} config(s) to '
                                                  f'{"plugin" if choice == 0 else "local"}', bool(n))
        except Exception as e:  # noqa: BLE001 — surface, don't crash
            note = f'error: {e}'
        return Intent(note=note)
