'''components.py — the Components screen (the default view) as a Screen (build_vm/draw/handle).

The richest screen and the most coupled to the session's inspection state: a pin / execute / refresh
re-probes and rebinds the shared (ms, cfg, ledger, states, diags) tuple, and a view-MODE switch
rebinds (ms, states, layouts, transitive). Rather than mutate loop-scope locals, handle performs the
reprobe and returns the new tuple(s) on the Intent (reloaded / remodeled), which the router adopts —
so the shared state has exactly one owner.

The model is the existing MenuState, composed as self.model. build_vm carries the frame inputs the
painter needs (the status note + diagnostics); draw reproduces the legacy _draw cell for cell (the
tree, header chips, infoblock, legends); handle is the former fall-through dispatch.
'''

import curses

from .. import menu
from ..menu import (COMPONENT, COMPONENT_MODES, LINK, OPS, PROFILE, STATUS_COLOR, UNIT,
                    _COMP_OPS, _REFRESH_WARN_DAYS, _columns, _components_model, _confirm_and_execute,
                    _draw_nav, _fill_bg, _filter_edit, _find_edit_tree, _fit, _identity_line,
                    _infoblock, _methods_line, _node_component, _offer_method_swap, _page_rows,
                    _pick_choices, _put, _rebuild_menu, _reload, _row_component, _scope_is_choice,
                    _scroll_reveal, _scroll_top, _scrollbar_v)
from ..screen import suspended
from .base import Intent, Screen, ViewModel

_KIND_ELEM = {PROFILE: 'profile', LINK: 'link', COMPONENT: 'component', UNIT: 'unit'}

# Actions we intercept when the cursor sits inside the System Updates subtree: i/u (and their -all
# forms) trigger the whole-machine bulk upgrade; the rest are inapplicable and just explain themselves.
_SU_BULK_ACTS = {'op-install', 'op-upgrade', 'op-install-all', 'op-upgrade-all'}
_SU_NA_ACTS = {'op-remove', 'select', 'method', 'where', 'lock'}


def _cursor_in_sysupd(ms):
    '''True when the cursor is on a System Updates node (its group, a tier, or a package row) — every
    such member carries the `system_update` flag.'''
    node = ms.cur()
    return bool(node and node.members
                and all(m.component.fields.get('system_update') for m in node.members))


def _lock_verb(ms):
    '''"unlock" when pressing the lock key would UNLOCK the current target (any of its present units
    is locked, or a lock is staged); "lock" otherwise. So the footer legend reads `L unlock` while a
    locked component (e.g. a held jdk) is focused — the toggle's other direction stops being invisible
    — and `L lock` the rest of the time (width-neutral).'''
    for node in ms._target_nodes():
        for m in node.members:
            if not (m.supported and m.present):
                continue
            staged = ms.staged.get(m.key)
            if staged == 'lock' or (m.locked and staged != 'unlock'):
                return 'unlock'
    return 'lock'


class ComponentsVM(ViewModel):
    '''Frame inputs the Components painter reads beyond the model: the status note + the diagnostics
    list (for the header attention badge). The tree/infoblock content is read from the model in draw
    (a deeper pure extraction is a later pass — this screen's win is the render seam + handle).'''

    def __init__(self, note='', diags=()):
        self.note = note
        self.diags = diags


class ComponentsScreen(Screen):
    id = 'components'

    def __init__(self, ctx, model):
        self.ctx = ctx
        self.model = model
        self.note = ''
        self.diags = ()

    def build_vm(self, ctx, size):
        return ComponentsVM(self.note, self.diags)

    # -- draw (reproduces menu._draw for screen == 'components') -----------

    def draw(self, surface, pal, vm):
        ms, ctx, note, diags = self.model, self.ctx, vm.note, vm.diags
        screen = 'components'
        surface.erase()
        h, w = surface.getmaxyx()
        cols = _columns(w)
        descriptions = getattr(ms, 'descriptions', None) or {}
        pal.use_page(screen)
        if pal.gradient:
            _fill_bg(surface, pal, h, w)
        _draw_nav(surface, pal, screen, h, w)
        title = ' configsys '
        _put(surface, 1, 0, title, pal.style('label', 1, 0, h, w))
        sub = f'  {ctx.os_info.block}'
        if ctx.runner.pretend:
            sub += '   [PRETEND]'
        sub += f'   view: {getattr(ms, "mode", "to-do")}'
        _put(surface, 1, len(title), _fit(sub, max(1, w - len(title))), pal.style('os', 1, len(title), h, w))
        rend = len(title) + len(sub)
        from ... import refreshstate
        age = refreshstate.age_days(ctx.paths)
        if age is None:
            rtext, relem = 'index never refreshed', 'issue_warning'
        elif age < 1:
            rtext, relem = 'index refreshed today', 'info_dim'
        else:
            rtext, relem = f'index refreshed {int(age)}d ago', \
                'issue_warning' if age >= _REFRESH_WARN_DAYS else 'info_dim'
        rx = rend + 3
        if rx < w - 4:
            _put(surface, 1, rx, _fit(rtext, max(1, w - rx - 1)), pal.style(relem, 1, rx, h, w))
            rend = rx + len(rtext)
        reb = getattr(ctx, '_reboot_pending', None)
        if reb and reb[0]:
            btext = '  ⚠ reboot advised'
            if rend + len(btext) < w - 1:
                _put(surface, 1, rend, btext, pal.style('issue_warning', 1, rend, h, w))
                rend += len(btext)
        from ... import sysupdates
        # the 3-space gap is left UNSTYLED (page bg) so a chip's own background doesn't bleed into the
        # separator between chips — only the glyph text carries the element colour.
        _su_gap = 3
        if getattr(ctx, '_sysupd_groups', None) is None:   # scan not done yet -> animated placeholder
            import time
            spin = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'[int(time.time() * 10) % 10]
            label = f'{spin} checking system updates…'
            if rend + _su_gap + len(label) < w - 1:
                _put(surface, 1, rend + _su_gap, label, pal.style('info_dim', 1, rend + _su_gap, h, w))
                rend += _su_gap + len(label)
        else:
            su_n = sysupdates.cached_total(ctx)
            if su_n:
                label = f'⟳ {su_n} system update{"s" if su_n != 1 else ""}'
                if rend + _su_gap + len(label) < w - 1:
                    _put(surface, 1, rend + _su_gap, label,
                         pal.style('issue_warning', 1, rend + _su_gap, h, w))
                    rend += _su_gap + len(label)
        if diags:
            n = len(diags)
            elem = 'issue_error' if any(d['level'] == 'error' for d in diags) else 'issue_warning'
            badge = f' ⚠ {n} issue{"s" if n != 1 else ""} — press ! to view '
            bx = max(rend + 2, w - len(badge) - 1)
            _put(surface, 1, bx, _fit(badge, w - bx), pal.style(elem, 1, bx, h, w))

        for c, text in (('name', 'component'), ('driver', 'driver'), ('scope', 'scope'),
                        ('status', 'status'), ('inst', 'installed'), ('latest', 'latest')):
            x, cw = cols[c]
            _put(surface, 2, x, _fit(text, cw), pal.style('menu_header', 2, x, h, w))

        list_top = 3
        list_h = max(1, h - list_top - 6)
        if ms.reveal is not None:
            pi = next((i for i, n in enumerate(ms.rows) if n.id == ms.reveal), None)
            if pi is not None:
                pd, end = ms.rows[pi].depth, pi
                for j in range(pi + 1, len(ms.rows)):
                    if ms.rows[j].depth > pd:
                        end = j
                    else:
                        break
                ms.top = _scroll_reveal(pi, end, ms.top, list_h, len(ms.rows))
            ms.reveal = None
        ms.top = first = _scroll_top(ms.cursor, ms.top, list_h, len(ms.rows))

        for vis, i in enumerate(range(first, min(len(ms.rows), first + list_h))):
            n = ms.rows[i]
            y = list_top + vis
            sel = i == ms.cursor

            def col(c, s, element, pad=True):
                x, cw = cols[c]
                _put(surface, y, x, (_fit(s, cw).ljust(cw) if pad else _fit(s, cw)),
                     pal.style(element, y, x, h, w, selected=sel))

            marker_sel = '»' if n.id in ms.selected else ' '
            op = ms.node_op(n)
            err = ms.row_error(n)
            if op:
                bch, belem = (op if op == '*' else OPS[op][0]), ('op_mixed' if op == '*' else 'op_' + op)
            elif err:
                bch, belem = '✗', 'row_error'
            else:
                bch, belem = ' ', 'unit'

            marker = ('▾ ' if n.expanded else '▸ ') if n.expandable else '  '
            name = '  ' * n.depth + marker + n.label

            if sel:
                _put(surface, y, 0, ' ' * (w - 1), pal.fill(y, 0, h, w, selected=True))
            _put(surface, y, 0, marker_sel, pal.style('select_marker', y, 0, h, w, selected=sel))
            _put(surface, y, 1, bch, pal.style(belem, y, 1, h, w, selected=sel))
            nx, ncw = cols['name']
            _put(surface, y, nx, _fit(name, ncw).ljust(ncw),
                 pal.style(_KIND_ELEM.get(n.kind, 'unit'), y, nx, h, w, selected=sel))
            rc = _node_component(n)
            rdesc = descriptions.get(rc, '') if rc else ''
            davail = ncw - len(name) - 2
            if rdesc and davail >= 6:
                _put(surface, y, nx + len(name) + 2, _fit(rdesc, davail),
                     pal.style('row_desc', y, nx + len(name) + 2, h, w, selected=sel))
            col('driver', n.driver, 'driver')
            col('scope', n.scope_str(), 'scope_choice' if _scope_is_choice(n) else 'scope')
            col('status', n.status, n.status if n.status in STATUS_COLOR else 'unit')
            if err:
                ix = cols['inst'][0]
                _put(surface, y, ix, _fit(err, max(1, w - ix - 1)),
                     pal.style('row_error', y, ix, h, w, selected=sel))
            else:
                col('inst', n.installed_str(), 'version')
                col('latest', n.latest_str(), 'version', pad=False)
        _scrollbar_v(surface, pal, list_top, w - 1, list_h, ms.top, list_h, len(ms.rows), h, w)

        _put(surface, h - 6, 0, _fit(_identity_line(ms, ctx, descriptions), w),
             pal.style('info', h - 6, 0, h, w))
        _put(surface, h - 5, 0, _fit(_methods_line(ms, ctx), w), pal.style('methods', h - 5, 0, h, w))
        _put(surface, h - 4, 0, _fit(_infoblock(ms, ctx), w), pal.style('info_dim', h - 4, 0, h, w))

        status_line = f' selected:{len(ms.selected)}  staged:{len(ms.staged)}'
        if ms.filter:
            status_line += f'   filter:{ms.filter}'
        if note:
            status_line += f'   {note}'
        km = menu._KEYMAP
        if km is not None:
            g = lambda a: km.glyph('components', a)
            nav = (f" {g('down')}/{g('up')} move · {g('top')}/{g('bottom')} top/bottom · "
                   f"{g('right')}/{g('left')} expand/collapse · {g('confirm')} open · {g('find')} find · "
                   f"{g('filter')} filter · {g('expand-all')} expand-all ")
            act = (f" {g('select')} sel · {g('select-all')} all · {g('op-install')}/{g('op-install-all')} inst · "
                   f"{g('op-upgrade')}/{g('op-upgrade-all')} upg · {g('op-remove')} rm · {g('lock')} {_lock_verb(ms)} · "
                   f"{g('method')} via · {g('where')} where · {g('clear')} clear · {g('execute')} exec · "
                   f"{g('refresh')} refresh · {g('issues')} issues · {g('quit')} quit ")
        else:
            nav = ' j/k · g/G top/bottom · l/h expand/collapse · enter open · / find · F filter · tab expand-all '
            act = (' space sel · a all · i/I inst · u/U upg · x rm · L ' + _lock_verb(ms) +
                   ' · v via · w where · c clear · X exec · R refresh · ! issues · q quit ')
        _put(surface, h - 3, 0, _fit(status_line, w), pal.style('status_line', h - 3, 0, h, w))
        _put(surface, h - 2, 0, _fit(nav.ljust(w), w), pal.style('footer', h - 2, 0, h, w))
        _put(surface, h - 1, 0, _fit(act.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
        surface.refresh()

    # -- handle (reproduces the components fall-through dispatch) ----------

    def handle(self, ch, ctx, stdscr, pal, cfg, ledger):
        '''One key. Mutates the model; for pin/execute/refresh/clear it re-probes and returns the new
        (ms, cfg, ledger, states, diags) on Intent.reloaded; for a MODE switch, the new
        (ms, states, layouts, transitive) on Intent.remodeled — the router adopts them.'''
        ms = self.model
        km = menu._KEYMAP
        act = km.action_for('components', ch) if km is not None else None
        intent = Intent()
        if _cursor_in_sysupd(ms):                       # System Updates: bulk-action, no per-row staging
            if act in _SU_BULK_ACTS:                    # i/u stages them ALL (all-or-nothing); X applies
                n = ms.stage_system_updates()
                intent.note = (f'staged {n} system update{"s" if n != 1 else ""} — press X to apply (bulk)'
                               if n else 'no system updates to apply')
                return intent
            if act in _SU_NA_ACTS:
                intent.note = 'System Updates apply in bulk — i/u stages them all, then X applies'
                return intent
        if act == 'down':
            ms.move(1)
        elif act == 'up':
            ms.move(-1)
        elif act == 'page-down':
            ms.move(_page_rows(stdscr))
        elif act == 'page-up':
            ms.move(-_page_rows(stdscr))
        elif act == 'top':
            ms.go_top()
        elif act == 'bottom':
            ms.go_bottom()
        elif act == 'where':
            _wname = _row_component(ms.cur())
            if _wname:
                from ...app import where_report
                lines = where_report(ctx, _wname) or [f'{_wname}: nothing to show']
                intent.open_where = (lines, _wname)
        elif act == 'filter':
            _filter_edit(stdscr, ms.filter, ms.set_filter,
                         lambda: self.draw(stdscr, pal, self.build_vm(ctx, stdscr.getmaxyx())))
        elif act == 'find':
            _find_edit_tree(stdscr, ms,
                            lambda: self.draw(stdscr, pal, self.build_vm(ctx, stdscr.getmaxyx())))
        elif act == 'confirm':
            ms.enter()
        elif act == 'right':
            ms.expand_or_jump()
        elif act == 'left':
            ms.collapse()
        elif act == 'lock':                                # L — toggles BOTH ways (lock <-> unlock)
            if not ms.toggle_lock():
                intent.note = 'nothing to lock/unlock here'
        elif act == 'expand-all':
            ms.toggle_expand_all()
        elif act == 'select':
            ms.toggle_select()
        elif act == 'select-all':
            ms.select_all()
        elif act == 'clear':
            _tgt = {ms.states[m.key].component.comp for node in ms._target_nodes()
                    for m in node.members if m.key in ms.states}
            ms.unstage()
            ms.clear_selection()
            ms.errors.clear()
            _dropped = _tgt & ctx.config.uninstall_queue()
            if _dropped:
                from ... import actions as _act
                for _c in _dropped:
                    _act.stage_uninstall(ctx, _c, on=False)
                try:
                    new = _reload(ctx, ms, set())
                    self.model = new[0]
                    intent.reloaded = new
                    intent.note = f'unstaged {len(_dropped)} from !uninstall'
                except Exception as e:  # noqa: BLE001
                    intent.note = f'reload failed: {e}'
        elif act == 'method':
            changed, note, deferred = _pick_choices(stdscr, pal, ms, ctx)
            intent.note = note
            if deferred:
                intent.pending_notes = [deferred]
            if changed:
                ctx.invalidate()
                try:
                    new = _reload(ctx, ms, set())
                    self.model = ms = new[0]
                    intent.reloaded = new
                    _swap = _offer_method_swap(stdscr, pal, ms, ctx)
                    if _swap:
                        intent.note = _swap
                except Exception as e:  # noqa: BLE001
                    intent.note = f'reload failed: {e}'
        elif act in _COMP_OPS:
            if not ms.stage(_COMP_OPS[act]):
                intent.note = f'{_COMP_OPS[act]} not applicable here'
        elif act == 'op-install-all':
            n = ms.stage_all('install')
            intent.note = (f'staged install/upgrade on {n} component(s) — run with execute'
                           if n else 'everything tracked is installed and current')
        elif act == 'op-upgrade-all':
            n = ms.stage_all('upgrade')
            intent.note = (f'staged {n} upgrade(s) — run with execute'
                           if n else 'nothing outdated to upgrade')
        elif act == 'execute':
            executed, note, outcomes = _confirm_and_execute(stdscr, pal, ms, ctx, ledger)
            intent.note = note
            curses.flushinp()
            if executed:
                failed = {o.key: f'{o.op} failed: {o.detail}' for o in outcomes if not o.ok}
                bad = [o for o in outcomes if not o.ok]
                if bad:
                    intent.pending_report = bad[-1].key.split('\\', 1)[-1]
                try:
                    touched = {o.key for o in outcomes}
                    new = _reload(ctx, ms, touched)
                    self.model = ms = new[0]
                    intent.reloaded = new
                except Exception as e:  # noqa: BLE001
                    intent.note = f'reload failed: {e}'
                ms.staged.clear()
                ms.errors = failed
                if ctx.config.reboot_advice():
                    from ... import rebootcheck
                    ctx._reboot_pending = rebootcheck.reboot_pending(ctx)
                    if ctx._reboot_pending[0]:
                        intent.note = ((intent.note + '   ' if intent.note else '')
                                       + f'⚠ reboot advised — {ctx._reboot_pending[1]}')
                intent.invalidate_ps_overlay = True
                curses.flushinp()
        elif act == 'mode':
            nxt = COMPONENT_MODES[(COMPONENT_MODES.index(getattr(ms, 'mode', 'to-do')) + 1)
                                  % len(COMPONENT_MODES)]
            try:
                states, layouts, transitive = _components_model(
                    ctx, cfg, dict(ms.states), nxt, caches=ms._overlay_caches)
                new_ms = _rebuild_menu(ms, states, layouts, transitive, nxt)
                self.model = new_ms
                intent.remodeled = (new_ms, states, layouts, transitive)
            except Exception as e:  # noqa: BLE001
                intent.note = f'mode switch failed: {e}'
            else:
                intent.note = f'view: {nxt}'
        elif act == 'refresh':
            with suspended(stdscr):
                print('Refreshing the package view — re-querying version sources and running the\n'
                      'package-manager index update. This takes a moment; sudo may prompt below.\n',
                      flush=True)
                from ... import app
                app.cmd_refresh(ctx, None)
                try:
                    input('\n[Enter] to return')
                except EOFError:
                    pass
            curses.flushinp()
            self.note, self.diags = 'updating latest versions…', ms.states and self.diags
            self.draw(stdscr, pal, self.build_vm(ctx, stdscr.getmaxyx()))
            try:
                new = _reload(ctx, ms, set(ms.states))
                self.model = new[0]
                intent.reloaded = new
            except Exception as e:  # noqa: BLE001
                intent.note = f'reload failed: {e}'
            else:
                intent.note = 'refreshed version caches + package index'
        return intent
