'''components.py — the Components screen (the default view) as a Screen (build_vm/draw/handle).

The richest screen and the most coupled to the session's inspection state: a pin / execute / refresh
re-probes and rebinds the shared (ms, cfg, ledger, states, diags) tuple, and a view-MODE switch
rebinds (ms, states, layouts, transitive). Rather than mutate loop-scope locals, handle performs the
reprobe and returns the new tuple(s) on the Intent (reloaded / remodeled), which the router adopts —
so the shared state has exactly one owner.

The model is the existing MenuState, composed as self.model. build_vm settles the whole frame from
it, ctx and the frame size — the title-row chips, the column header, the tree's visible rows as
positioned cells, the three cursor lines, the status line and legends (review-2026-11-2 D7); draw
only paints that; handle dispatches one key through the keymap.
'''

import curses

from ... import primarygit, refreshstate, sysupdates
from .. import menu
from ..flows import _confirm_and_execute, _offer_method_swap, _pick_choices, _reload
from ..modals import _filter_edit, _find_edit_tree
from ..models import (
    _COMP_OPS, _identity_line, _infoblock, _methods_line, _REFRESH_WARN_DAYS,
    _row_component, _scope_is_choice, _switch_mode, COMPONENT, COMPONENT_MODES, LINK, OPS, PROFILE,
    UNIT)
from ..paint import _columns, _fit, _page_rows, _put, _reveal_subtree, _scroll_top, _scrollbar_v
from ..screen import suspended
from ..theme import STATUSES
from .base import Intent, Screen, ViewModel

_KIND_ELEM = {PROFILE: 'profile', LINK: 'link', COMPONENT: 'component', UNIT: 'unit'}

# Actions we intercept when the cursor sits inside the System Updates subtree: i/u (and their -all
# forms) trigger the whole-machine bulk upgrade; the rest are inapplicable and just explain themselves.
_SU_BULK_ACTS = {'op-install', 'op-upgrade', 'op-install-all', 'op-upgrade-all'}
_SU_NA_ACTS = {'op-remove', 'select', 'method', 'where', 'lock'}


def _rescan_system_updates(ctx, ms, *, before_reload):
    '''Re-gather the System Updates scan after something changed what's upgradable (a refresh, an
    execute). Called twice around the _reload: `before_reload=True` drops the cached scan
    (sysupdates.invalidate) so the rebuilt tree no longer injects the stale rows, returning how many
    SU rows were staged (their marks go with the rows); `before_reload=False` starts the background
    re-scan (sysupdates.start_scan), which the router folds in when it lands.'''
    if before_reload:
        n = sum(1 for k in ms.staged if sysupdates.is_synthetic(ms.states.get(k)))
        sysupdates.invalidate(ctx)
        return n
    sysupdates.start_scan(ctx)
    return 0


def _cursor_in_sysupd(ms):
    '''True when the cursor is on a System Updates node (its group, a tier, or a package row) — every
    such member carries the `system_update` flag.'''
    node = ms.cur()
    return bool(node and node.members
                and all(m.component.fields.get('system_update') for m in node.members))


def _su_dim(node):
    '''True for a System Updates package row that is an AUTO-PULLED dependency in the standard/apps
    tiers — dimmed so the handful you actually chose stand out. kernel/core rows are never dimmed
    (a libc/kernel bump stays prominent even though it's technically an auto "essential").'''
    if node.kind != UNIT or not node.members:
        return False
    f = node.members[0].component.fields
    return bool(f.get('su_auto')) and f.get('su_tier') in ('standard', 'apps')


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
    '''Everything one Components frame paints, settled by build_vm from the model, ctx and the frame
    size — draw decides nothing (review-2026-11-2 D7 / tui-screens-07): the title row's chips, the
    column header, the tree's visible rows as positioned cells, the three cursor lines, the status
    line and the two legend rows.'''

    def __init__(self, note='', diags=(), primary_chip='', refresh_age=None):
        self.note = note
        self.diags = diags
        self.primary_chip = primary_chip           # "prim: ↑2 to push, ↓1 to sync", or ''
        self.refresh_age = refresh_age             # days since the package index refresh (None: never)
        self.chips = []                            # row 1: [(x, text, role)]
        self.col_header = []                       # row 2: [(x, text)]
        self.list_top, self.list_h = 3, 1          # the tree's window
        self.top, self.n = 0, 0                    # its scroll offset and total rows (scrollbar)
        self.rows = []                             # [TreeRow] — the visible window
        self.cursor_lines = []                     # [(text, role)] — identity, methods, infoblock
        self.status = ''
        self.legends = []                          # the two legend rows


class TreeRow:
    '''One tree row: [(x, text, role)] cells, and whether it is the cursor row (selection fill).'''
    __slots__ = ('cells', 'sel')

    def __init__(self, cells, sel):
        self.cells, self.sel = cells, sel


class ComponentsScreen(Screen):
    id = 'components'

    def __init__(self, ctx, model):
        self.ctx = ctx
        self.model = model
        self.note = ''
        self.diags = ()

    def build_vm(self, ctx, size):
        ms = getattr(self, 'model', None)
        h, w = size
        policy = primarygit.PUSH_POLICY[getattr(ctx, '_primary_push_mode', 'ask')]
        chip = primarygit.chip(getattr(ctx, '_primary_state', None), hide_ahead=policy['hide_ahead'])
        age = refreshstate.age_days(ctx.paths) if ctx is not None else None
        vm = ComponentsVM(self.note, self.diags, chip, age)
        if ms is None or ctx is None:                  # no tree to show (only the frame inputs)
            return vm
        cols = _columns(w)
        descriptions = getattr(ms, 'descriptions', None) or {}
        self._chips_vm(vm, ms, ctx, w)
        vm.col_header = [(cols[c][0], _fit(text, cols[c][1]))
                         for c, text in (('name', 'component'), ('driver', 'driver'), ('scope', 'scope'),
                                         ('status', 'status'), ('inst', 'installed'), ('latest', 'latest'))]
        vm.list_h = max(1, h - vm.list_top - 6)
        first = ms.top
        if ms.reveal is not None:                        # a just-expanded node -> reveal its subtree
            first = _reveal_subtree([n.id for n in ms.rows], [n.depth for n in ms.rows], ms.reveal,
                                    first, vm.list_h)
        first = _scroll_top(ms.cursor, first, vm.list_h, len(ms.rows))
        vm.top, vm.n = first, len(ms.rows)
        vm.settle(top=first, reveal=None, page_h=vm.list_h)   # page_h: what PgDn/PgUp move by
        for i in range(first, min(len(ms.rows), first + vm.list_h)):
            vm.rows.append(self._tree_row(ms.rows[i], i == ms.cursor, ms, cols, descriptions, w))
        vm.cursor_lines = [(_identity_line(ms, ctx, descriptions), 'info'),
                           (_methods_line(ms, ctx), 'methods'),
                           (_infoblock(ms, ctx), 'info_dim')]
        vm.status = (f' selected:{len(ms.selected)}  staged:{len(ms.staged)}'
                     + (f'   filter:{ms.filter}' if ms.filter else '')
                     + (f'   {vm.note}' if vm.note else ''))
        g = lambda a: menu._keymap().glyph('components', a)
        vm.legends = [
            (f" {g('down')}/{g('up')} move · {g('top')}/{g('bottom')} top/bottom · "
             f"{g('right')}/{g('left')} expand/collapse · {g('confirm')} open · {g('find')} find · "
             f"{g('filter')} filter · {g('expand-all')} expand-all "),
            (f" {g('select')} sel · {g('select-all')} all · {g('op-install')}/{g('op-install-all')} inst · "
             f"{g('op-upgrade')}/{g('op-upgrade-all')} upg · {g('op-remove')} rm · {g('lock')} {_lock_verb(ms)} · "
             f"{g('method')} via · {g('where')} where · {g('clear')} clear · {g('execute')} exec · "
             f"{g('refresh')} refresh · {g('issues')} issues · {g('quit')} quit ")]
        return vm

    def _chips_vm(self, vm, ms, ctx, w):
        '''Row 1: the title, the OS / pretend / curating / view line, then the status chips — index
        age, reboot advice, the primary's push state, system updates, the issues badge — each placed
        only while it fits.'''
        chips = vm.chips
        title = ' configsys '
        chips.append((0, title, 'label'))
        sub = f'  {ctx.os_info.block}'
        if ctx.runner.pretend:
            sub += '   [PRETEND]'
        other = ctx.curating_machine() if hasattr(ctx, 'curating_machine') else None
        if other:
            sub += f'   machine: {other} (curating — installs off)'
        sub += f'   view: {getattr(ms, "mode", "to-do")}'
        chips.append((len(title), _fit(sub, max(1, w - len(title))), 'os'))
        rend = len(title) + len(sub)
        age = vm.refresh_age
        if age is None:
            rtext, relem = 'index never refreshed', 'issue_warning'
        elif age < 1:
            rtext, relem = 'index refreshed today', 'info_dim'
        else:
            rtext, relem = (f'index refreshed {int(age)}d ago',
                            'issue_warning' if age >= _REFRESH_WARN_DAYS else 'info_dim')
        rx = rend + 3
        if rx < w - 4:
            chips.append((rx, _fit(rtext, max(1, w - rx - 1)), relem))
            rend = rx + len(rtext)
        reb = getattr(ctx, '_reboot_pending', None)
        if reb and reb[0]:
            btext = '  ⚠ reboot advised'
            if rend + len(btext) < w - 1:
                chips.append((rend, btext, 'issue_warning'))
                rend += len(btext)
        ptext = vm.primary_chip
        if ptext and rend + 3 + len(ptext) < w - 1:      # your primary has changes to push / sync
            chips.append((rend + 3, ptext, 'outdated'))
            rend += 3 + len(ptext)
        # the 3-space gap is left UNSTYLED (page bg) so a chip's own background doesn't bleed into the
        # separator between chips — only the glyph text carries the element colour.
        gap = 3
        if getattr(ctx, '_sysupd_groups', None) is None:   # scan not done yet -> animated placeholder
            # spinner frame from the loop's monotonic tick (NOT the clock), so a frame is deterministic
            spin = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'[getattr(ctx, '_frame', 0) % 10]
            label, role = f'{spin} checking system updates…', 'info_dim'
        else:
            su_n = sysupdates.cached_total(ctx)
            label, role = (f'⟳ {su_n} system update{"s" if su_n != 1 else ""}' if su_n else ''), 'issue_warning'
        if label and rend + gap + len(label) < w - 1:
            chips.append((rend + gap, label, role))
            rend += gap + len(label)
        if vm.diags:
            n = len(vm.diags)
            elem = 'issue_error' if any(d['level'] == 'error' for d in vm.diags) else 'issue_warning'
            badge = (f' ⚠ {n} issue{"s" if n != 1 else ""} — press '
                     f'{menu._keymap().glyph("global", "issues")} to view ')
            bx = max(rend + 2, w - len(badge) - 1)
            chips.append((bx, _fit(badge, w - bx), elem))

    @staticmethod
    def _tree_row(n, sel, ms, cols, descriptions, w):
        '''One visible tree row as positioned cells: the select marker, the staged-op / error glyph,
        the indented name (+ its description where it fits), driver, scope, status, versions.'''
        def col(c, s, role, pad=True):
            x, cw = cols[c]
            return (x, _fit(s, cw).ljust(cw) if pad else _fit(s, cw), role)

        op = ms.node_op(n)
        err = ms.row_error(n)
        if op:
            bch, belem = (op if op == '*' else OPS[op][0]), ('op_mixed' if op == '*' else OPS[op][1])
        elif err:
            bch, belem = '✗', 'row_error'
        else:
            bch, belem = ' ', 'unit'
        marker = ('▾ ' if n.expanded else '▸ ') if n.expandable else '  '
        name = '  ' * n.depth + marker + n.label
        dim = _su_dim(n)                                 # auto-pulled system-update dep -> recede it
        nx, ncw = cols['name']
        cells = [(0, '»' if n.id in ms.selected else ' ', 'select_marker'),
                 (1, bch, belem),
                 (nx, _fit(name, ncw).ljust(ncw), 'info_dim' if dim else _KIND_ELEM.get(n.kind, 'unit'))]
        rc = _row_component(n)
        rdesc = descriptions.get(rc, '') if rc else ''
        davail = ncw - len(name) - 2
        if rdesc and davail >= 6:
            cells.append((nx + len(name) + 2, _fit(rdesc, davail), 'row_desc'))
        cells += [col('driver', n.driver, 'driver'),
                  col('scope', n.scope_str(), 'scope_choice' if _scope_is_choice(n) else 'scope'),
                  col('status', n.status, 'info_dim' if dim else
                      (n.status if n.status in STATUSES else 'unit'))]
        if err:
            ix = cols['inst'][0]
            cells.append((ix, _fit(err, max(1, w - ix - 1)), 'row_error'))
        else:
            cells += [col('inst', n.installed_str(), 'info_dim' if dim else 'version'),
                      col('latest', n.latest_str(), 'info_dim' if dim else 'version', pad=False)]
        return TreeRow(cells, sel)

    # -- draw -------------------------------------------------------------

    def draw(self, surface, pal, vm):
        h, w = self.begin_page(surface, pal)
        for x, text, role in vm.chips:
            _put(surface, 1, x, text, pal.style(role, 1, x, h, w))
        for x, text in vm.col_header:
            _put(surface, 2, x, text, pal.style('menu_header', 2, x, h, w))
        for vis, row in enumerate(vm.rows):
            y = vm.list_top + vis
            if row.sel:
                _put(surface, y, 0, ' ' * (w - 1), pal.fill(y, 0, h, w, selected=True))
            for x, text, role in row.cells:
                _put(surface, y, x, text, pal.style(role, y, x, h, w, selected=row.sel))
        _scrollbar_v(surface, pal, vm.list_top, w - 1, vm.list_h, vm.top, vm.list_h, vm.n, h, w)
        for k, (text, role) in enumerate(vm.cursor_lines):
            y = h - 6 + k
            _put(surface, y, 0, _fit(text, w), pal.style(role, y, 0, h, w))
        self.end_page(surface, pal, vm.status, vm.legends, h, w)

    # -- handle -----------------------------------------------------------

    def handle(self, ch, ctx, stdscr, pal, cfg, ledger):
        '''One key. Mutates the model; for pin/execute/refresh/clear it re-probes and returns the new
        (ms, cfg, ledger, states, diags) on Intent.reloaded; for a MODE switch, the new
        (ms, states, layouts, transitive) on Intent.remodeled — the router adopts them.'''
        ms = self.model
        km = menu._keymap()
        act = km.action_for('components', ch)
        intent = Intent()
        if _cursor_in_sysupd(ms):                       # System Updates: bulk-action, no per-row staging
            if act in _SU_BULK_ACTS:                    # i/u stages them ALL (all-or-nothing); X applies
                n = ms.stage_system_updates()
                intent.note = (f'staged {n} system update{"s" if n != 1 else ""} — press '
                               f'{km.glyph("components", "execute")} to apply (bulk)'
                               if n else 'no system updates to apply')
                return intent
            if act in _SU_NA_ACTS:
                intent.note = (f'System Updates apply in bulk — {km.glyph("components", "op-install")}/'
                               f'{km.glyph("components", "op-upgrade")} stages them all, then '
                               f'{km.glyph("components", "execute")} applies')
                return intent
        if act == 'down':
            ms.move(1)
        elif act == 'up':
            ms.move(-1)
        elif act == 'page-down':
            ms.move(_page_rows(stdscr, getattr(ms, 'page_h', None)))
        elif act == 'page-up':
            ms.move(-_page_rows(stdscr, getattr(ms, 'page_h', None)))
        elif act == 'top':
            ms.go_top()
        elif act == 'bottom':
            ms.go_bottom()
        elif act == 'where':
            _wname = _row_component(ms.cur())
            if _wname:
                from ...cli.where import where_report
                lines = where_report(ctx, _wname) or [f'{_wname}: nothing to show']
                intent.open_where = (lines, _wname)
        elif act == 'filter':
            _filter_edit(stdscr, ms.filter, ms.set_filter,
                         lambda: self.render(stdscr, pal, ctx))
        elif act == 'find':
            _find_edit_tree(stdscr, ms,
                            lambda: self.render(stdscr, pal, ctx))
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
            _su_before = sum(1 for k in ms.staged if menu._is_system_update(ms.states.get(k)))
            ms.unstage()                                   # System Updates: all-or-nothing (see unstage)
            _su_after = sum(1 for k in ms.staged if menu._is_system_update(ms.states.get(k)))
            if _su_before and not _su_after:
                intent.note = (f'unstaged all {_su_before} system update(s) — they apply in bulk, '
                               'all or nothing')
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
                    intent.note = menu._pretend_note(   # --pretend: the queue edit wasn't saved
                        ctx, f'unstaged {len(_dropped)} from !uninstall', True)
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
        elif (act in _COMP_OPS or act in ('op-install-all', 'op-upgrade-all', 'execute')) \
                and getattr(ctx, 'curating_machine', lambda: None)():
            # B16 / parity-03: --machine <other> curates that machine's picks from here; installing
            # them HERE would be the surprise the CLI's `--picks` refuses
            intent.note = (f'read-only: you are curating {ctx.curating_machine()} (--machine) — '
                           'installs happen only for this box; edit its picks on Profiles')
        elif act in _COMP_OPS:
            if not ms.stage(_COMP_OPS[act]):
                intent.note = (getattr(ms, 'skip_note', '')
                               or f'{_COMP_OPS[act]} not applicable here')
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
                    # a System Updates bulk upgrade (`system-updates\\<mgr>`) changed EVERY package of
                    # that manager — requery all its units (and drop its cached installed index), not
                    # just the synthetic key, or they'd keep their pre-upgrade versions
                    bulk = {k.partition('\\')[2] for k in touched if k.startswith('system-updates\\')}
                    if bulk:
                        touched |= {k for k, st in ms.states.items() if st.component.driver in bulk}
                    # what's upgradable changed (a bulk upgrade, or a package op pulling deps) ->
                    # drop the stale System Updates scan before the rebuild, re-gather after it
                    _rescan_system_updates(ctx, ms, before_reload=True)
                    new = _reload(ctx, ms, touched)
                    self.model = ms = new[0]
                    intent.reloaded = new
                except Exception as e:  # noqa: BLE001
                    intent.note = f'reload failed: {e}'
                _rescan_system_updates(ctx, ms, before_reload=False)
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
                new_ms, states, layouts, transitive = _switch_mode(ctx, cfg, ms, nxt)
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
                from ...cli import refresh as cli_refresh
                cli_refresh.cmd_refresh(ctx)
                try:
                    input('\n[Enter] to return')
                except EOFError:
                    pass
            curses.flushinp()
            self.note, self.diags = 'updating latest versions…', self.diags if ms.states else ()
            self.render(stdscr, pal, ctx)
            # the package index just changed -> the System Updates scan (group + header count chip) is
            # stale too: drop it BEFORE the reload (so the rebuilt tree doesn't re-inject the old rows;
            # the header shows the 'checking' spinner), then re-gather in the background — the router
            # polls while it runs and folds the fresh group in when it lands.
            su_dropped = _rescan_system_updates(ctx, ms, before_reload=True)
            try:
                new = _reload(ctx, ms, set(ms.states))
                self.model = new[0]
                intent.reloaded = new
            except Exception as e:  # noqa: BLE001
                intent.note = f'reload failed: {e}'
            else:
                intent.note = 'refreshed version caches + package index' + (
                    f' — {su_dropped} staged system update(s) cleared: re-stage after the rescan'
                    if su_dropped else '')
            _rescan_system_updates(ctx, ms, before_reload=False)
        return intent
