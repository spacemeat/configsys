'''plugins.py — the Plugins screen as a Screen (build_vm/draw/handle).

First screen migrated off the monolithic menu.py painter (docs/d2-mvvm-plan.md). The model is the
existing `menu.PluginScreen` (state + git/trust ops), composed unchanged; this adds the three MVVM
seams:

- build_vm: computes the PURE render content — every table cell + its role, column widths, the remote
  strings, the selected diff file's header and role-tagged lines, and the status/nav strings. No
  curses, no geometry that needs the drawn borders.
- draw: lays the content out (panel rects, scroll clamps, scrollbars via the shared widgets) and
  paints it — no decisions the VM didn't already settle. It reproduces menu._draw_plugins cell for
  cell, which test_screen_plugins pins against the legacy painter.
- handle: the former `if screen == 'plugins'` dispatch, returning an Intent (note / dirty) instead of
  mutating loop-scope locals.
'''

from .. import menu
from ..menu import (_DIFF_ELEM, _PLUGIN_HEADERS, PluginScreen, _draw_nav, _fill_bg, _fit,
                    _input_box, _page_rows, _panel, _plugin_cells, _plugin_code_elem,
                    _plugin_remote_elem, _put, _put_hscroll, _scroll_top, _scrollbar_h, _scrollbar_v)
from ..screen import suspended
from .base import Intent, Screen, ViewModel


class PluginsVM(ViewModel):
    '''Pure render content for one Plugins frame — settled by build_vm, painted by draw.'''

    def __init__(self):
        self.has_rows = False
        self.empty_msg = ''
        # table content (scroll-independent)
        self.cells = []            # list[list[str]] — 7 columns per row
        self.widths = []           # column widths
        self.xs = []               # column virtual-x starts
        self.virt_w = 0
        self.elems = []            # list[list[str]] — role name per cell
        self.headers = _PLUGIN_HEADERS
        # diff content
        self.diff_title = 'diff'
        self.diff_has_files = False
        self.diff_msg = ''         # shown when there are no files
        self.diff_header = ''      # the [i/n] path +A -B line
        self.diff_lines = []       # list[(elem, text)] of the selected file
        self.diff_maxlen = 0
        # chrome
        self.status = ''
        self.nav = ''
        self.focus = 'table'


def _nav_str():
    km = menu._KEYMAP
    if km is not None:
        g = lambda a: km.glyph('plugins', a)
        return (f" {g('switch-pane')} focus · {g('down')}/{g('up')} · {g('left')}/{g('right')} scroll · "
                f"{g('add')} add · {g('remove')} rm · {g('sync')}/{g('sync-all')} sync · "
                f"{g('bless')}/{g('unbless')} bless · {g('update')}/{g('update-all')} update · "
                f"{g('set-ref')} ref · {g('trust')} trust · {g('trust-all')} trust-all · {g('quit')} ")
    return (' tab focus · j/k · h/l scroll · a add · x rm · s/S sync · b/B bless · u/U update · '
            'v ref · t trust · T trust-all · q ')


class PluginsScreen(Screen):
    id = 'plugins'

    def __init__(self, ctx, model=None):
        self.ctx = ctx
        self.model = model if model is not None else PluginScreen(ctx)

    def reload(self):
        self.model.reload()

    # -- build_vm ---------------------------------------------------------

    def build_vm(self, ctx, size):
        from ... import plugins
        pl = self.model
        vm = PluginsVM()
        vm.focus = pl.focus
        vm.has_rows = bool(pl.rows)
        if not pl.rows:
            vm.empty_msg = '(no plugins declared — a to add)'
        else:
            remotes = [pl.remote.get(plugins.dir_name(r['source'])) for r in pl.rows]
            vm.cells = [_plugin_cells(r, pl.tree[i], remotes[i]) for i, r in enumerate(pl.rows)]
            vm.widths = [max(len(_PLUGIN_HEADERS[c]), max((len(cs[c]) for cs in vm.cells), default=0))
                         for c in range(len(_PLUGIN_HEADERS))]
            vx = 0
            for wd in vm.widths:
                vm.xs.append(vx)
                vx += wd + 1
            vm.virt_w = vx - 1
            for i, row in enumerate(pl.rows):
                healthy = row['synced'] and row['abi_ok'] and row['checksum'] != 'mismatch'
                base = 'component' if healthy else 'info_dim'
                vm.elems.append([base, 'info_dim', 'info', _plugin_remote_elem(row, remotes[i]),
                                 'installed' if row['abi_ok'] else 'error', _plugin_code_elem(row),
                                 'info_dim'])
        self._build_diff_vm(vm)
        vm.status = f' {len(pl.rows)} plugin(s) · focus: {pl.focus}'
        vm.nav = _nav_str()
        return vm

    def _build_diff_vm(self, vm):
        from ... import plugins
        pl = self.model
        row = pl.cur_row()
        if row is not None:
            remote = pl.remote.get(plugins.dir_name(row['source']))
            to = remote if isinstance(remote, str) else '—'
            vm.diff_title = f'diff · {row["name"]} · {row["ref"] or "HEAD"} → {to}'
        files = pl.diff_files
        if not files:
            vm.diff_msg = pl.diff_note or 'Tab here to review what an update would change'
            return
        vm.diff_has_files = True
        pl.dfile = max(0, min(pl.dfile, len(files) - 1))
        f = files[pl.dfile]
        added = sum(1 for k, _t in f['lines'] if k == 'add')
        removed = sum(1 for k, _t in f['lines'] if k == 'del')
        vm.diff_header = (f'[{pl.dfile + 1}/{len(files)}] {f["path"]}   '
                          f'+{added} -{removed}   (Tab: next file)')
        vm.diff_lines = [(_DIFF_ELEM.get(k, 'info_dim'), t) for k, t in f['lines']]
        vm.diff_maxlen = max((len(t) for _k, t in f['lines']), default=0)

    # -- draw -------------------------------------------------------------

    def draw(self, surface, pal, vm):
        pl = self.model
        surface.erase()
        h, w = surface.getmaxyx()
        pal.use_page('plugins')
        if pal.gradient:
            _fill_bg(surface, pal, h, w)
        _draw_nav(surface, pal, 'plugins', h, w)
        top, body_h = 1, h - 3
        table_h = max(6, body_h * 2 // 5)
        diff_h = body_h - table_h
        self._draw_table(surface, pal, vm, h, w, top, table_h)
        self._draw_diff(surface, pal, vm, h, w, top + table_h, diff_h)
        status = vm.status
        _put(surface, h - 2, 0, _fit(status, w), pal.style('status_line', h - 2, 0, h, w))
        _put(surface, h - 1, 0, _fit(vm.nav.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
        surface.refresh()

    def _draw_table(self, surface, pal, vm, h, w, top, table_h):
        pl = self.model
        tit, til, tih, tiw = _panel(surface, pal, top, 0, table_h, w, 'plugins (tree)',
                                    pl.focus == 'table', h, w)
        if not vm.has_rows:
            _put(surface, tit, til, _fit(vm.empty_msg, tiw), pal.style('info_dim', tit, til, h, w))
            return
        pl.hscroll = max(0, min(pl.hscroll, max(0, vm.virt_w - tiw)))
        for hdr, vx0 in zip(vm.headers, vm.xs):
            _put_hscroll(surface, tit, til, tiw, vx0, pl.hscroll, hdr,
                         pal.style('menu_header', tit, til, h, w))
        rows_h = tih - 1
        pl.top = _scroll_top(pl.cur, pl.top, rows_h, len(pl.rows))
        for vis, i in enumerate(range(pl.top, min(len(pl.rows), pl.top + rows_h))):
            y, sel = tit + 1 + vis, i == pl.cur
            if sel:
                _put(surface, y, til, ' ' * tiw, pal.fill(y, til, h, w, selected=True))
            for cell, wd, vx0, el in zip(vm.cells[i], vm.widths, vm.xs, vm.elems[i]):
                style = pal.style('label' if sel else el, y, til, h, w, selected=sel)
                _put_hscroll(surface, y, til, tiw, vx0, pl.hscroll, cell.ljust(wd), style)
        _scrollbar_v(surface, pal, tit + 1, til + tiw, rows_h, pl.top, rows_h, len(pl.rows), h, w)
        _scrollbar_h(surface, pal, tit + table_h - 1, til, tiw, pl.hscroll, tiw, vm.virt_w, h, w)

    def _draw_diff(self, surface, pal, vm, h, w, top, diff_h):
        pl = self.model
        dit, dil, dih, diw = _panel(surface, pal, top, 0, diff_h, w, vm.diff_title,
                                    pl.focus == 'diff', h, w)
        if not vm.diff_has_files:
            _put(surface, dit, dil, _fit(vm.diff_msg, diw), pal.style('info_dim', dit, dil, h, w))
            return
        _put(surface, dit, dil, _fit(vm.diff_header, diw), pal.style('accent', dit, dil, h, w))
        body_h = dih - 1
        lines = vm.diff_lines
        pl.dtop = max(0, min(pl.dtop, max(0, len(lines) - body_h)))
        pl.dhscroll = max(0, min(pl.dhscroll, max(0, vm.diff_maxlen - diw)))
        for vis, i in enumerate(range(pl.dtop, min(len(lines), pl.dtop + body_h))):
            elem, txt = lines[i]
            y = dit + 1 + vis
            _put(surface, y, dil, _fit(txt[pl.dhscroll:], diw), pal.style(elem, y, dil, h, w))
        _scrollbar_v(surface, pal, dit + 1, dil + diw, body_h, pl.dtop, body_h, len(lines), h, w)
        _scrollbar_h(surface, pal, dit + diff_h - 1, dil, diw, pl.dhscroll, diw, vm.diff_maxlen, h, w)

    # -- handle -----------------------------------------------------------

    def handle(self, ch, ctx, stdscr, pal):
        '''One key. Mutates the model, runs git/trust ops (under `suspended` where they own the
        terminal), returns an Intent(note, dirty). Ported verbatim from the former plugins dispatch.'''
        from ... import actions, plugins
        pl = self.model
        row = pl.cur_row()
        km = menu._KEYMAP
        pact = km.action_for('plugins', ch) if km is not None else None
        note = None
        dirty = False
        try:
            if pl.focus == 'diff' and pl.diff_key is None:
                pl.load_diff()
            if pact == 'switch-pane':
                if pl.focus == 'table':
                    pl.focus, pl.dfile = 'diff', 0
                    pl.load_diff()
                elif pl.dfile + 1 < len(pl.diff_files):
                    pl.dfile, pl.dtop, pl.dhscroll = pl.dfile + 1, 0, 0
                else:
                    pl.focus = 'table'
            elif pact == 'switch-pane-back':
                if pl.focus == 'table':
                    pl.focus = 'diff'
                    pl.load_diff()
                    pl.dfile = max(0, len(pl.diff_files) - 1)
                elif pl.dfile > 0:
                    pl.dfile, pl.dtop, pl.dhscroll = pl.dfile - 1, 0, 0
                else:
                    pl.focus = 'table'
            elif pact == 'down':
                if pl.focus == 'diff':
                    pl.dtop += 1
                else:
                    pl.cur = min(len(pl.rows) - 1, pl.cur + 1); pl._invalidate_diff()
            elif pact == 'up':
                if pl.focus == 'diff':
                    pl.dtop = max(0, pl.dtop - 1)
                else:
                    pl.cur = max(0, pl.cur - 1); pl._invalidate_diff()
            elif pact == 'page-down':
                if pl.focus == 'diff':
                    pl.dtop += _page_rows(stdscr)
                else:
                    pl.cur = min(len(pl.rows) - 1, pl.cur + _page_rows(stdscr)); pl._invalidate_diff()
            elif pact == 'page-up':
                if pl.focus == 'diff':
                    pl.dtop = max(0, pl.dtop - _page_rows(stdscr))
                else:
                    pl.cur = max(0, pl.cur - _page_rows(stdscr)); pl._invalidate_diff()
            elif pact == 'right':
                if pl.focus == 'diff':
                    pl.dhscroll += 4
                else:
                    pl.hscroll += 6
            elif pact == 'left':
                if pl.focus == 'diff':
                    pl.dhscroll = max(0, pl.dhscroll - 4)
                else:
                    pl.hscroll = max(0, pl.hscroll - 6)
            elif pact == 'top':
                if pl.focus == 'diff':
                    pl.dtop = 0
                else:
                    pl.cur = 0; pl._invalidate_diff()
            elif pact == 'bottom':
                if pl.focus == 'diff':
                    pl.dtop = 10 ** 6
                else:
                    pl.cur = max(0, len(pl.rows) - 1); pl._invalidate_diff()
            elif pact == 'add':
                src, replace = _input_box(
                    stdscr, pal, 'add plugin — source (github:owner/repo)', '',
                    toggle=('replace an existing plugin of the same name (retarget)', False))
                if src and src.strip():
                    with suspended(stdscr):
                        _ok, msg, _r = actions.plugin_add(ctx, src.strip(), replace=replace)
                    pl.reload()
                    dirty = True
                    note = msg.split('\n')[0]
            elif pact == 'remove' and row:
                _ok, note = actions.plugin_remove(ctx, row['name'])
                pl.reload()
                dirty = True
            elif pact == 'sync' and row:
                tgt = [t['decl'] for t in pl.tree
                       if plugins.dir_name(t['decl']['source']) == plugins.dir_name(row['source'])]
                with suspended(stdscr):
                    actions.plugin_sync(ctx, tgt)
                pl.reload()
                dirty = True
                note = f'synced {row["name"]}'
            elif pact == 'sync-all':
                with suspended(stdscr):
                    actions.plugin_sync(ctx, plugins.declared(ctx.paths.user_config_file))
                pl.reload()
                dirty = True
                note = 'synced all'
            elif pact == 'bless' and row:
                with suspended(stdscr):
                    _ok, msg, _r = actions.plugin_bless(ctx, row['source'])
                pl.reload()
                dirty = True
                note = msg
            elif pact == 'unbless':
                _ok, note = actions.plugin_unbless(ctx)
                pl.reload()
                dirty = True
            elif pact == 'update' and row:
                with suspended(stdscr):
                    _ok, msg, _r = actions.plugin_update(ctx, row['name'], latest=True)
                pl.reload()
                dirty = _ok
                note = msg
            elif pact == 'update-all':
                with suspended(stdscr):
                    rows_ = actions.plugin_update_all(ctx, latest=True)
                pl.reload()
                dirty = True
                failed = [s for s, ok, _m in rows_ if not ok]
                note = f'updated {len(rows_) - len(failed)}/{len(rows_)} to latest' + (
                    f' ({len(failed)} failed)' if failed else '')
            elif pact == 'trust' and row:
                if row['code_state'] == 'trusted':
                    _ok, note = actions.plugin_untrust(ctx, row['name'])
                else:
                    _ok, note = actions.plugin_trust(ctx, row['name'])
                pl.reload()
                dirty = _ok
            elif pact == 'trust-all':
                _n, note = actions.plugin_trust_all(ctx)
                pl.reload()
                dirty = bool(_n)
            elif pact == 'set-ref' and row:
                ref = _input_box(stdscr, pal, f'{row["name"]} — set ref (tag/branch/sha)', '')
                if ref and ref.strip():
                    with suspended(stdscr):
                        _ok, msg, _r = actions.plugin_update(ctx, row['name'], ref.strip())
                    pl.reload()
                    dirty = True
                    note = msg
        except Exception as e:  # noqa: BLE001 — surface, don't crash
            note = f'error: {e}'
        return Intent(note=note, dirty=dirty)
