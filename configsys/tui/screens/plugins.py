'''plugins.py — the Plugins screen as a Screen (build_vm/draw/handle).

First screen migrated off the monolithic menu.py painter (docs/done/d2-mvvm-plan.md). The model is the
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

import os

from .. import menu
from ..menu import (_DIFF_ELEM, _PLUGIN_HEADERS, PluginScreen, _fit, _input_box, _page_rows,
                    _panel, _plugin_cells, _plugin_code_elem, _plugin_remote_elem, _put,
                    _scrollbar_h, _scrollbar_v)
from ..screen import suspended
from . import table
from .base import Intent, Screen, ViewModel, results_note


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
        self.display = None        # rows in order (no section rules)
        # diff content
        self.diff_title = 'diff'
        self.diff_has_files = False
        self.diff_msg = ''         # shown when there are no files
        self.diff_header = ''      # the [i/n] path +A -B line
        self.diff_lines = []       # list[(elem, text)] of the selected file
        self.diff_maxlen = 0
        # chrome
        self.status = ''
        self.note = ''             # the transient action note (the host supplies it; '' when none)
        self.nav = ''
        self.focus = 'table'


def _nav_str():
    g = lambda a: menu._keymap().glyph('plugins', a)
    return (f" {g('switch-pane')} focus · {g('down')}/{g('up')} · {g('left')}/{g('right')} scroll · "
            f"{g('add')} add · {g('remove')} rm · {g('sync')}/{g('sync-all')} sync · "
            f"{g('bless')}/{g('unbless')} bless · {g('update')}/{g('update-all')} update · "
            f"{g('set-ref')} ref · {g('trust')} trust · {g('trust-all')} trust-all · "
            f"{g('lock')} lock · {g('push')} push · {g('history')} history · {g('quit')} ")


def _history(stdscr, pal, ctx, pl):
    '''Plugins `H`: the primary's recent changes in a list (↑ not pushed, * made by configsys), with
    "Undo …" for the newest configsys change on top. Returns the note to show.'''
    from ... import primarygit
    found = primarygit.history(ctx, 15)
    if found is None:
        return 'no synced primary plugin on a branch'
    name, changes = found
    last = primarygit.undoable(changes)
    rows = [(f'{"↑" if not c.pushed else " "}{"*" if c.by_configsys else " "} {c.date}  {c.subject}', c.short)
            for c in changes]
    opts = ([(f'Undo "{last.subject}"', 'z')] if last else []) + rows
    pick = menu._popup_choose(stdscr, pal, f'{name}: recent changes (↑ not pushed · * made by configsys)',
                              opts, start=0, shortcuts={'z': 0} if last else None)
    if not last or pick != 0:
        return None
    files = ', '.join(last.files[:4]) + (' …' if len(last.files) > 4 else '')
    other = last.machine and last.machine != primarygit._machine(ctx)
    sure = menu._popup_choose(stdscr, pal, f'Undo "{last.subject}"'
                                           + (f' (made on {last.machine}, not this machine)' if other else '')
                                           + f'? ({files}) — a file it added is saved '
                                           f'to <state>/undo/{last.short}/ first',
                              [('Undo it', 'y'), ('Keep it', 'n')], start=1, shortcuts={'y': 0, 'n': 1})
    if sure != 0:
        return None
    _ok, lines = primarygit.undo(ctx)
    ctx.invalidate()
    pl.reload()
    pl._set_primary_state(primarygit.state(ctx))
    return lines[-1] if lines else None


def _sync_note(ctx, results):
    '''The first sync outcome that needs explaining (kept / diverged / ahead), for the status line.'''
    from ... import plugins
    from ...cli.plugin import _primary_dir_name
    prim = _primary_dir_name(ctx)
    for name, action in results or ():
        note = plugins.sync_note(name, action, ctx.paths.plugins_dir, primary=name == prim)
        if note:
            return note
    return None


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
            pst = getattr(pl, 'primary_state', None)
            vm.cells = [_plugin_cells(r, pl.tree[i], remotes[i], pst) for i, r in enumerate(pl.rows)]
            vm.widths, vm.xs, vm.virt_w = table.layout(_PLUGIN_HEADERS, vm.cells, gutter=1)
            for i, row in enumerate(pl.rows):
                healthy = row['synced'] and row['abi_ok'] and row['checksum'] != 'mismatch'
                base = 'component' if healthy else 'info_dim'
                vm.elems.append([base, 'info_dim', 'info', _plugin_remote_elem(row, remotes[i], pst),
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
        span = getattr(pl, 'diff_span', None)
        if row is not None and span:
            frm, to, what = span
            vm.diff_title = f'diff · {row["name"]} · {frm} → {to} · {what}'
        elif row is not None:
            remote = pl.remote.get(plugins.dir_name(row['source']))
            to = remote if isinstance(remote, str) else '—'
            vm.diff_title = f'diff · {row["name"]} · {row["ref"] or "HEAD"} → {to}'
        files = pl.diff_files
        if not files:
            vm.diff_msg = pl.diff_note or 'Tab here to review what an update would change'
            return
        vm.diff_has_files = True
        dfile = max(0, min(pl.dfile, len(files) - 1))
        vm.settle(dfile=dfile)
        f = files[dfile]
        added = sum(1 for k, _t in f['lines'] if k == 'add')
        removed = sum(1 for k, _t in f['lines'] if k == 'del')
        vm.diff_header = (f'[{dfile + 1}/{len(files)}] {f["path"]}   '
                          f'+{added} -{removed}   (Tab: next file)')
        vm.diff_lines = [(_DIFF_ELEM.get(k, 'info_dim'), t) for k, t in f['lines']]
        vm.diff_maxlen = max((len(t) for _k, t in f['lines']), default=0)

    # -- draw -------------------------------------------------------------

    def draw(self, surface, pal, vm):
        h, w = self.begin_page(surface, pal)
        top, body_h = 1, h - 3
        table_h = max(6, body_h * 2 // 5)
        diff_h = body_h - table_h
        self._draw_table(surface, pal, vm, h, w, top, table_h)
        self._draw_diff(surface, pal, vm, h, w, top + table_h, diff_h)
        self.end_page(surface, pal, vm.status + (f'    {vm.note}' if vm.note else ''), [vm.nav], h, w)

    def _draw_table(self, surface, pal, vm, h, w, top, table_h):
        pl = self.model
        tit, til, tih, tiw = _panel(surface, pal, top, 0, table_h, w, 'plugins (tree)',
                                    pl.focus == 'table', h, w)
        if not vm.has_rows:
            _put(surface, tit, til, _fit(vm.empty_msg, tiw), pal.style('info_dim', tit, til, h, w))
            return
        top, hscroll = table.draw_table(surface, pal, (tit, til, tih, tiw), vm, pl.cur,
                                        pl.top, pl.hscroll, h, w)
        vm.settle(top=top, hscroll=hscroll)

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
        dtop = max(0, min(pl.dtop, max(0, len(lines) - body_h)))
        dhscroll = max(0, min(pl.dhscroll, max(0, vm.diff_maxlen - diw)))
        vm.settle(dtop=dtop, dhscroll=dhscroll)
        for vis, i in enumerate(range(dtop, min(len(lines), dtop + body_h))):
            elem, txt = lines[i]
            y = dit + 1 + vis
            _put(surface, y, dil, _fit(txt[dhscroll:], diw), pal.style(elem, y, dil, h, w))
        _scrollbar_v(surface, pal, dit + 1, dil + diw, body_h, dtop, body_h, len(lines), h, w)
        _scrollbar_h(surface, pal, dit + dih, dil, diw, dhscroll, diw, vm.diff_maxlen, h, w)

    # -- handle -----------------------------------------------------------

    def handle(self, ch, ctx, stdscr, pal):
        '''One key. Mutates the model, runs git/trust ops (under `suspended` where they own the
        terminal), returns an Intent(note, dirty). Ported verbatim from the former plugins dispatch.'''
        from ... import actions, plugins
        pl = self.model
        row = pl.cur_row()
        km = menu._keymap()
        pact = km.action_for('plugins', ch)
        note = None
        dirty = False
        pending = []
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
            elif pact in menu._NAV_ACTIONS:
                if pl.focus == 'diff':                  # the diff scroll is clamped by the draw
                    pl.dtop = menu.ListNav.apply(pact, pl.dtop, 10 ** 6, lambda: _page_rows(stdscr))
                else:
                    pl.cur = menu.ListNav.apply(pact, pl.cur, len(pl.rows) - 1, lambda: _page_rows(stdscr))
                    pl._invalidate_diff()
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
            elif pact == 'add':
                src, replace = _input_box(
                    stdscr, pal, 'add plugin — source (github:owner/repo, a git URL, or a local path)', '',
                    toggle=('replace an existing plugin of the same name (retarget)', False))
                if src and src.strip():
                    src = src.strip()
                    # a local path (a project checkout) is THIS machine's — it can't sync anywhere else
                    # (§7 default; G3); a remote source with a primary blessed: ask where it goes
                    local = src.startswith(('/', '~', '.', 'file:')) or os.path.isdir(os.path.expanduser(src))
                    prim = plugins.primary_name(plugins.declared(ctx.paths.user_config_file))
                    if not local and prim:
                        where = menu._popup_choose(stdscr, pal, f'add {src} for …',
                                                   [(f'all your machines (in {prim})', ''),
                                                    ('this machine only', '')], 0)
                        if where is None:
                            return Intent(note='not added')
                        local = where == 1
                    ref = _input_box(stdscr, pal, f'{src} — ref (tag / branch / sha; empty = its default)', '')
                    with suspended(stdscr):
                        _ok, msg, _r = actions.plugin_add(ctx, src, (ref or '').strip() or None,
                                                          local=local, replace=replace)
                    pl.reload()
                    dirty = True
                    note = msg.split('\n')[0]
            elif pact == 'picks-to-primary':
                n, label = actions.move_picks_to_primary(ctx)
                note = menu._pretend_note(ctx, (
                    'no primary plugin — picks already live in your top config' if label == 'no primary'
                    else f'moved {n} pick(s) into {label} — they travel to your other machines' if n
                    else f'nothing to move — no local picks (they already live in {label})'), bool(n))
                dirty = dirty or bool(n)
            elif pact == 'set-source' and row:
                cur = row.get('source', '')
                new = _input_box(stdscr, pal, f'{row["name"]} — new source (e.g. github:you/{row["name"]})', cur)
                if new and new.strip() and new.strip() != cur:
                    import argparse
                    from ...cli.plugin import cmd_plugin_set_source
                    with suspended(stdscr):
                        rc = cmd_plugin_set_source(ctx, argparse.Namespace(name=row['name'], source=new.strip()),
                                                   plugins.declared(ctx.paths.user_config_file))
                    pl.reload()
                    dirty = True
                    note = (f'{row["name"]} now syncs from {new.strip()}' if rc == 0
                            else f'{row["name"]}: source unchanged')
            elif pact == 'init-primary':
                import argparse
                from ...cli.plugin import cmd_plugin_init
                decls = plugins.declared(ctx.paths.user_config_file)
                name = None
                if not plugins.primary_name(decls):
                    name = _input_box(stdscr, pal, 'new primary plugin — name', '')
                    if name is None:
                        return Intent(note='no primary made')
                with suspended(stdscr):               # show the plan, then ask, on the plain terminal
                    a = argparse.Namespace(name=(name or '').strip() or None, force=False, dry_run=True)
                    cmd_plugin_init(ctx, a, decls)
                    try:
                        go = input('\nGo ahead? [y/N] ').strip().lower() == 'y'
                    except EOFError:
                        go = False
                    rc = cmd_plugin_init(ctx, argparse.Namespace(**{**vars(a), 'dry_run': False}), decls) if go else None
                pl.reload()
                dirty = dirty or rc == 0
                note = ('plugin init done' if rc == 0 else 'plugin init: nothing changed' if rc is None
                        else 'plugin init failed — see the output above')
            elif pact == 'remove' and row:
                _ok, note = actions.plugin_remove(ctx, row['name'])
                pl.reload()
                dirty = True
            elif pact == 'sync' and row:
                tgt = [t['decl'] for t in pl.tree
                       if plugins.dir_name(t['decl']['source']) == plugins.dir_name(row['source'])]
                with suspended(stdscr):
                    res = actions.plugin_sync(ctx, tgt)
                pl.reload()
                dirty = True
                note = (f'{row["name"]} is locked — not synced (L unlocks)'
                        if res and res[0][1] == 'locked' else
                        _sync_note(ctx, res) or f'synced {row["name"]}')
            elif pact == 'sync-all':
                with suspended(stdscr):
                    res = actions.plugin_sync(ctx, plugins.declared(ctx.paths.user_config_file))
                pl.reload()
                dirty = True
                note = _sync_note(ctx, res) or results_note(
                    ctx, 'synced', [(n, plugins.sync_succeeded(a), str(a)) for n, a in (res or [])],
                    what='plugin(s)', nothing='no plugins declared')
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
            elif pact == 'lock' and row:
                if row.get('locked'):
                    _ok, note = actions.plugin_unlock(ctx, row['name'])
                else:
                    _ok, note = actions.plugin_lock(ctx, row['name'])
                pl.reload()
            elif pact == 'push':
                _ok, lines = menu._push_primary(stdscr, pal, ctx)
                pl.reload()
                note = lines[-1] if lines else None
                pending = lines[:-1]
            elif pact == 'history':
                note = _history(stdscr, pal, ctx, pl)
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
        try:
            pl.load_diff()               # the review diff follows the cursor (fetched in the background)
        except Exception as e:  # noqa: BLE001
            note = note or f'error: {e}'
        return Intent(note=note, dirty=dirty, pending_notes=pending)
