'''menu.py — MenuState (pure interaction logic) + curses view + run loop.

The menu is a three-level tree:
  profile  (expanded by default)
    └─ component   (a profile entry, e.g. `vulkan-dev`; collapsed by default)
         └─ unit   (the concrete install units, e.g. apt\\libxcb-xinput0)

A component that resolves to a single unit is shown as a leaf (no expansion). One
with dependencies/parts expands to reveal them, individually selectable. Ops can be
staged on any node — a profile stages all its units, a component its units, a unit
just itself — and staging is keyed by unit, so a mark is consistent everywhere the
unit appears. Enter/→ expand, ← collapse, Tab expands/collapses all components.
'''

import curses

from .. import reportgen
from ..drivers import get_driver, scope_meta
from ..planning import expand_plan
from .screen import curses_screen, suspended
from .theme import STATUS_COLOR, Palette

# op -> (single-char badge, palette color, predicate on a ComponentState)
OPS = {
    'install': ('I', 'op_install', lambda s: s.supported and not s.present),
    'upgrade': ('U', 'op_upgrade', lambda s: s.supported and s.outdated),
    'remove':  ('X', 'op_remove',  lambda s: s.supported and s.present),
    'lock':    ('L', 'op_lock',    lambda s: s.supported and s.present and not s.locked),
    'unlock':  ('l', 'op_unlock',  lambda s: s.supported and s.locked),
}

KEY_TO_OP = {
    ord('i'): 'install', ord('u'): 'upgrade', ord('x'): 'remove',
}

PROFILE, COMPONENT, UNIT, LINK = 'profile', 'component', 'unit', 'link'


class Node:
    def __init__(self, kind, id, label, depth, members, *, driver='',
                 expandable=False, expanded=False, link_target=None):
        self.kind = kind
        self.id = id
        self.label = label
        self.depth = depth
        self.members = members       # list[ComponentState] this node covers
        self.driver = driver
        self.expandable = expandable
        self.expanded = expanded
        self.link_target = link_target   # id of a profile node this LINK jumps to (item 1)
        self.parent = None               # set by _build_tree (for collapse-to-parent)
        self.children = []

    # -- aggregate state over members -------------------------------------

    @property
    def status(self):
        ms = self.members
        supported = [m for m in ms if m.supported]
        if not supported:
            return 'unsupported'
        if any(m.error for m in ms):
            return 'error'
        if any(m.outdated for m in supported):
            return 'outdated'
        present = sum(1 for m in supported if m.present)
        if present == 0:
            return 'missing'
        if present < len(supported):
            return 'partial'
        if all(m.locked for m in supported):
            return 'locked'
        return 'installed'

    @property
    def locked(self):
        present = [m for m in self.members if m.supported and m.present]
        return bool(present) and all(m.locked for m in present)

    def installed_str(self):
        if self.kind == UNIT:
            m = self.members[0]
            if not m.supported:
                # untrusted: version is UNKNOWN (the tool may well be installed — we just can't
                # read it without the driver), not '—' which reads as "not installed".
                return '?' if m.untrusted else '—'
            v = m.installed_version or '—'
            return f'{v} [L]' if m.locked else v
        present = sum(1 for m in self.members if m.present)
        return f'{present}/{len(self.members)}'

    def latest_str(self):
        if self.kind == UNIT:
            m = self.members[0]
            if not m.supported:
                return '?' if m.untrusted else ''
            return m.latest_version or '—'
        return ''

    def scope_str(self):
        if self.kind == UNIT:
            return self.members[0].scope or ''
        # groups: show the scope only if every unit agrees
        scopes = {m.scope for m in self.members if m.scope}
        return next(iter(scopes)) if len(scopes) == 1 else ''

    def summary(self):
        present = sum(1 for m in self.members if m.present)
        return f'{self.label}: {present}/{len(self.members)} of its units installed'


class MenuState:
    def __init__(self, states, profile_comps):
        self.states = states               # {unit_key: ComponentState}
        self.profile_comps = profile_comps  # [(profile, [component_name, ...])]
        self._name_units = self._invert()
        self.roots = self._build_tree()
        self.rows = []
        self.cursor = 0
        self.top = 0                       # first visible row (persistent scroll offset)
        self.selected = set()              # node ids
        self.staged = {}                   # unit_key -> op
        self.errors = {}                   # unit_key -> message
        self._refresh()

    def _invert(self):
        name_units = {}
        for key, st in self.states.items():
            for name in st.component.requested_as:
                name_units.setdefault(name, []).append(key)
        return name_units

    def _build_tree(self):
        roots = []
        for profile, names in self.profile_comps:
            pnode = Node(PROFILE, f'p:{profile}', profile, 0, [],
                         expandable=True, expanded=True)
            pmembers = {}  # dedupe shared units in the profile aggregate (by key)
            for name in names:
                keys = sorted(self._name_units.get(name, []))
                members = [self.states[k] for k in keys]
                if not members:
                    continue
                if len(members) == 1:
                    m = members[0]
                    cnode = Node(UNIT, f'c:{profile}:{name}', name, 1, [m],
                                 driver=m.component.driver)
                else:
                    cnode = Node(COMPONENT, f'c:{profile}:{name}', name, 1, members,
                                 expandable=True, expanded=False)
                    for m in members:
                        unode = Node(UNIT, f'u:{profile}:{name}:{m.key}', m.component.comp,
                                     2, [m], driver=m.component.driver)
                        unode.parent = cnode
                        cnode.children.append(unode)
                for m in members:
                    pmembers[m.key] = m
                cnode.parent = pnode
                pnode.children.append(cnode)
            pnode.members = list(pmembers.values())
            roots.append(pnode)
        return roots

    # -- visible rows / expansion -----------------------------------------

    def _visible(self):
        out = []

        def walk(n):
            out.append(n)
            if n.expandable and n.expanded:
                for c in n.children:
                    walk(c)
        for r in self.roots:
            walk(r)
        return out

    def _all_nodes(self):
        '''Every node in the tree (visible or not) — for carrying expansion/selection across a
        rebuild.'''
        out = []

        def walk(n):
            out.append(n)
            for c in n.children:
                walk(c)
        for r in self.roots:
            walk(r)
        return out

    def _refresh(self, keep_id=None):
        self.rows = self._visible()
        if keep_id is not None:
            for i, n in enumerate(self.rows):
                if n.id == keep_id:
                    self.cursor = i
                    break
        self.cursor = max(0, min(self.cursor, len(self.rows) - 1)) if self.rows else 0

    def _all_components(self):
        out = []

        def walk(n):
            if n.kind == COMPONENT:
                out.append(n)
            for c in n.children:
                walk(c)
        for r in self.roots:
            walk(r)
        return out

    def cur(self):
        return self.rows[self.cursor] if self.rows else None

    def _goto(self, node_id):
        for i, n in enumerate(self.rows):
            if n.id == node_id:
                self.cursor = i
                return True
        return False

    def expand(self, want):
        n = self.cur()
        if n and n.expandable and n.expanded != want:
            n.expanded = want
            self._refresh(keep_id=n.id)

    def toggle_expand(self):
        n = self.cur()
        if n and n.expandable:
            self.expand(not n.expanded)

    def enter(self):
        '''Enter: a LINK jumps to its target profile; anything else toggles expansion.'''
        n = self.cur()
        if n and n.link_target:
            self._goto(n.link_target)
        else:
            self.toggle_expand()

    def expand_or_jump(self):
        '''l / →: a LINK jumps to its target; a collapsed expandable expands; an already-expanded
        one steps into its first child.'''
        n = self.cur()
        if n is None:
            return
        if n.link_target:
            self._goto(n.link_target)
        elif n.expandable and not n.expanded:
            n.expanded = True
            self._refresh(keep_id=n.id)
        elif n.expandable and n.expanded and n.children:
            self._goto(n.children[0].id)

    def collapse(self):
        '''h / ←: collapse an expanded node (profiles included); otherwise step to the parent.'''
        n = self.cur()
        if n is None:
            return
        if n.expandable and n.expanded:
            n.expanded = False
            self._refresh(keep_id=n.id)
        elif n.parent is not None:
            self._goto(n.parent.id)

    def toggle_expand_all(self):
        comps = self._all_components()
        want = any(not c.expanded for c in comps)  # expand all if any collapsed
        for c in comps:
            c.expanded = want
        keep = self.cur().id if self.cur() else None
        self._refresh(keep_id=keep)

    # -- navigation -------------------------------------------------------

    def move(self, delta):
        if self.rows:
            self.cursor = max(0, min(len(self.rows) - 1, self.cursor + delta))

    def top(self):
        self.cursor = 0

    def bottom(self):
        if self.rows:
            self.cursor = len(self.rows) - 1

    # -- selection --------------------------------------------------------

    def toggle_select(self):
        if self.rows:
            self.selected ^= {self.rows[self.cursor].id}

    def select_all(self):
        self.selected = {n.id for n in self.rows}

    def clear_selection(self):
        self.selected.clear()

    def _target_nodes(self):
        if self.selected:
            return [n for n in self.rows if n.id in self.selected]
        return [self.cur()] if self.cur() else []

    # -- staging (unit-keyed) ---------------------------------------------

    def stage(self, op):
        pred = OPS[op][2]
        staged_any = False
        for node in self._target_nodes():
            for m in node.members:
                if pred(m):
                    self.staged[m.key] = op
                    self.errors.pop(m.key, None)
                    staged_any = True
        return staged_any

    def toggle_lock(self):
        '''Toggle version-lock intent on the target units (present + supported). Unlocking removes
        a staged (requested) lock as well as staging an unlock for an actually-locked unit; locking
        removes a staged unlock as well as staging a lock for an unlocked unit. So one key flips
        both a pending request and a settled lock. `c` (clear) drops the staged op -> back to the
        current on-disk lock state.'''
        acted = False
        for node in self._target_nodes():
            for m in node.members:
                if not (m.supported and m.present):
                    continue
                staged = self.staged.get(m.key)
                effective_locked = staged == 'lock' or (m.locked and staged != 'unlock')
                if effective_locked:                       # -> unlock
                    if staged == 'lock':
                        self.staged.pop(m.key, None)       # undo a requested-but-unfulfilled lock
                    elif m.locked:
                        self.staged[m.key] = 'unlock'      # stage removal of a settled lock
                else:                                      # -> lock
                    if staged == 'unlock':
                        self.staged.pop(m.key, None)       # undo a requested unlock
                    elif not m.locked:
                        self.staged[m.key] = 'lock'
                self.errors.pop(m.key, None)
                acted = True
        return acted

    def unstage(self):
        for node in self._target_nodes():
            for m in node.members:
                self.staged.pop(m.key, None)

    def clear_all_staged(self):
        self.staged.clear()

    def plan(self):
        return [(op, k, self.states[k].component) for k, op in sorted(self.staged.items())]

    def node_op(self, node):
        ops = {self.staged[m.key] for m in node.members if m.key in self.staged}
        if not ops:
            return None
        return next(iter(ops)) if len(ops) == 1 else '*'

    def node_error(self, node):
        for m in node.members:
            if m.key in self.errors:
                return self.errors[m.key]
        return None

    def row_error(self, node):
        '''The op-error to SHOW on a row. Suppressed on PROFILE rows: a failed shared dependency
        (e.g. curl, required by every tarball) is a member of every profile that pulls a tarball
        app, so surfacing it there smears one failure across all of them. It stays on the
        component/unit rows where it is actually local and actionable.'''
        return None if node.kind == PROFILE else self.node_error(node)


# -- execution ------------------------------------------------------------

class OpOutcome:
    def __init__(self, op, key, name, ok, detail=''):
        self.op = op
        self.key = key
        self.name = name
        self.ok = ok
        self.detail = detail


def _fail_detail(res):
    '''A concise failure reason for a driver Result: exit code plus the last non-empty line of
    its output (stderr, else the tee'd tail of streamed output, else stdout) — so the TUI shows
    WHY, not a bare "exit 1". The full output is still persisted for `configsys report`.'''
    if res is None:
        return 'no result'
    text = (res.stderr or res.captured or res.stdout or '').strip()
    last = text.splitlines()[-1].strip() if text else ''
    return f'exit {res.returncode}: {last}' if last else f'exit {res.returncode}'


def execute_plan(ctx, plan, ledger):
    outcomes = []
    last_failure = None
    for op, key, rc in plan:
        fam = get_driver(rc.driver, ctx.runner, ctx.paths)
        if fam is None:
            print(f'skip {key}: driver "{rc.driver}" not yet supported')
            outcomes.append(OpOutcome(op, key, rc.name, False, 'unsupported driver'))
            continue

        print(f'\n>>> {op} {key} (pkg: {rc.name})')
        if op == 'install':
            res = fam.install(rc)
        elif op == 'upgrade':
            res = fam.upgrade(rc)
        elif op == 'remove':
            res = fam.uninstall(rc)
        elif op == 'lock':
            res = fam.lock(rc)
            if res.ok:
                ledger.set_lock(key, True)
        elif op == 'unlock':
            res = fam.unlock(rc)
            if res.ok:
                ledger.set_lock(key, False)
        else:
            res = None

        ok = bool(res and res.ok)
        detail = '' if ok else _fail_detail(res)
        if not ok and res is not None:
            last_failure = reportgen.failure_from_result(key, rc.driver, op, res)
        outcomes.append(OpOutcome(op, key, rc.name, ok, detail))

    ledger.save(ctx.paths)
    if last_failure is not None:           # persist for a post-quit `configsys report <c>`
        reportgen.save_failure(ctx.paths, last_failure)
    return outcomes


def _summary_note(outcomes):
    n_ok = sum(1 for o in outcomes if o.ok)
    n_bad = len(outcomes) - n_ok
    return f'{n_ok} ok' if n_bad == 0 else f'{n_ok} ok, {n_bad} failed'


def _confirm_and_execute(stdscr, pal, ms, ctx, ledger):
    raw = ms.plan()
    if not raw:
        return False, 'nothing staged', []
    units = {k: st.component for k, st in ms.states.items()}
    plan = expand_plan(raw, units, ms.states)

    with suspended(stdscr):
        print('\nAbout to execute:')
        for op, key, rc in plan:
            print(f'  {op:8} {key}  (pkg: {rc.name})')
        try:
            ans = input('\nProceed? [y/N] ').strip().lower()
        except EOFError:
            ans = 'n'
        if ans != 'y':
            print('cancelled.')
            input('Press Enter to return...')
            return False, 'cancelled', []

        outcomes = execute_plan(ctx, plan, ledger)
        n_ok = sum(1 for o in outcomes if o.ok)
        failed = [o for o in outcomes if not o.ok]
        print(f'\nSummary: {n_ok} ok, {len(failed)} failed')
        for o in failed:
            print(f'  FAILED  {o.op:8} {o.key}  (pkg: {o.name})  {o.detail}')
        input('\nPress Enter to return...')
        return True, _summary_note(outcomes), outcomes


# -- rendering ------------------------------------------------------------

def _columns(w):
    '''Responsive column geometry -> {col: (x, width)} for the given terminal width. NAME and
    FAMILY absorb the extra horizontal room; the two version columns (INSTALLED / LATEST) always
    get equal width. SCOPE/STATUS stay compact.'''
    start = 3                                     # after the select marker + op badge
    scope_w, status_w = 8, 9
    flex = max(24, (w - 1) - start - scope_w - status_w - 5)   # 5 inter-column gaps
    ver_w = max(8, min(18, flex // 5))            # INSTALLED == LATEST
    rest = max(22, flex - 2 * ver_w)              # NAME + FAMILY share the remainder
    name_w = max(14, rest * 3 // 5)
    fam_w = max(8, rest - name_w)
    nx = start
    fx = nx + name_w + 1
    scx = fx + fam_w + 1
    stx = scx + scope_w + 1
    ix = stx + status_w + 1
    lx = ix + ver_w + 1
    return {'name': (nx, name_w), 'fam': (fx, fam_w), 'scope': (scx, scope_w),
            'status': (stx, status_w), 'inst': (ix, ver_w), 'latest': (lx, ver_w)}


def _scroll_top(cursor, top, list_h, nrows):
    '''The first visible row, given a persistent scroll offset `top`: keep the cursor in view but
    only scroll when it leaves the window — so the cursor moves freely inside the viewport and
    sits on the bottom row only once the list is scrolled to its end (not pinned there the moment
    you page down). Clamped so the last page shows fully.'''
    if cursor < top:
        top = cursor
    elif cursor >= top + list_h:
        top = cursor - list_h + 1
    return max(0, min(top, max(0, nrows - list_h)))


def _fit(s, width):
    return s if len(s) <= width else s[:max(0, width - 1)] + '…'


def _put(stdscr, y, x, s, attr=0):
    h, w = stdscr.getmaxyx()
    if y < 0 or y >= h or x < 0 or x >= w:
        return
    s = s[:max(0, w - x)]
    try:
        stdscr.addstr(y, x, s, attr)
    except curses.error:
        pass


def _methods_line(ms, ctx):
    '''A line listing every install method eligible for the current component here — not just the
    default or the pin — with the default marked `*` and a pin marked. Blank unless there's a
    real choice (>=2). `m` opens the picker.'''
    name = _row_component(ms.cur())
    if not name:
        return ''
    cands = ctx.routes.candidates(name)
    if len(cands) < 2:
        return ''
    parts = []
    for c in cands:
        tag = c['via']
        if c['pinned']:
            tag += ' (pinned)'
        elif c['default']:
            tag += ' *'
        parts.append(tag)
    return f' methods: {"   ".join(parts)}      (m to change)'


def _infoblock(ms, ctx):
    '''Two detail lines for the current row: (1) full versions / lock state, (2) the
    install location on its own line (paths get long). Groups get a one-line summary.
    (The columns truncate these; here is where they show in full.)'''
    n = ms.cur()
    if n is None:
        return '', ''
    if n.kind != UNIT:
        return ' ' + n.summary(), ''
    m = n.members[0]
    rc = m.component
    if not m.supported:
        # `error` carries the right message: the trust hint for untrusted, else "not supported"
        return f' {rc.driver}\\{rc.comp}   ·   {m.error or "driver not yet supported"}', ''
    parts = [f'{rc.driver}\\{rc.comp}']
    if m.scope:
        parts.append(f'scope: {m.scope}')
    parts += [f'installed: {m.installed_version or "—"}',
              f'latest: {m.latest_version or "—"}']
    if m.locked:
        parts.append('version-locked')
    fam = get_driver(rc.driver, ctx.runner, ctx.paths)
    loc = fam.location(rc) if fam is not None else None
    return ' ' + '   ·   '.join(parts), (f' at: {loc}' if loc else '')


def _wrap(s, width):
    '''Hard char-wrap (paths rarely have useful word breaks), never empty.'''
    s, width = s or '', max(1, width)
    return [s[i:i + width] for i in range(0, len(s), width)] or ['']


def _draw_diagnostics(stdscr, pal, diags, top):
    '''The `!` page: every non-fatal skip/warning, scrollable. Returns the clamped scroll top.'''
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    _put(stdscr, 0, 0, _fit(f' configsys — diagnostics ({len(diags)}) ', w),
         pal.get('title') | curses.A_BOLD | curses.A_REVERSE)
    lines = []                                       # [(text, attr)]
    for d in diags:
        col = pal.get('error' if d['level'] == 'error' else 'outdated')
        mark = '✗' if d['level'] == 'error' else '⚠'
        lines.append((f'{mark} {d["tag"]}', col | curses.A_BOLD))
        for seg in _wrap(d['text'], w - 4):
            lines.append(('    ' + seg, pal.get('dim')))
        lines.append(('', curses.A_NORMAL))
    if not diags:
        lines = [('  no issues — everything loaded cleanly.', pal.get('installed'))]
    body_h = max(1, h - 3)
    top = max(0, min(top, max(0, len(lines) - body_h)))
    for i, (text, attr) in enumerate(lines[top:top + body_h]):
        _put(stdscr, 2 + i, 0, _fit(text, w), attr)
    foot = ' j/k scroll · g/G top/bottom · ! or q back '
    _put(stdscr, h - 1, 0, _fit(foot.ljust(w), w), pal.get('dim') | curses.A_REVERSE)
    stdscr.refresh()
    return top


def _draw(stdscr, pal, ms, ctx, note, diags=(), show_diag=False, diag_top=0):
    if show_diag:
        return _draw_diagnostics(stdscr, pal, diags, diag_top)
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    cols = _columns(w)

    # top line: the `configsys` chip, then the OS block (+ PRETEND) to its right, then the badge.
    title = ' configsys '
    _put(stdscr, 0, 0, title, pal.get('title') | curses.A_BOLD | curses.A_REVERSE)
    sub = f'  {ctx.os_info.block}'
    if ctx.runner.pretend:
        sub += '   [PRETEND]'
    _put(stdscr, 0, len(title), _fit(sub, max(1, w - len(title))), pal.get('header') | curses.A_BOLD)
    if diags:                                        # attention badge, right-aligned on the top line
        n = len(diags)
        lvl = 'error' if any(d['level'] == 'error' for d in diags) else 'outdated'
        badge = f' ⚠ {n} issue{"s" if n != 1 else ""} — press ! to view '
        bx = max(len(title) + len(sub) + 2, w - len(badge) - 1)
        _put(stdscr, 0, bx, _fit(badge, w - bx),
             pal.get(lvl) | curses.A_BOLD | curses.A_REVERSE)

    hattr = pal.get('dim') | curses.A_BOLD
    for col, text in (('name', 'COMPONENT'), ('fam', 'FAMILY'), ('scope', 'SCOPE'),
                      ('status', 'STATUS'), ('inst', 'INSTALLED'), ('latest', 'LATEST')):
        x, cw = cols[col]
        _put(stdscr, 1, x, _fit(text, cw), hattr)

    list_top = 2
    list_h = max(1, h - list_top - 6)  # methods + 2 infoblock + status + 2 footer lines
    ms.top = first = _scroll_top(ms.cursor, ms.top, list_h, len(ms.rows))

    for vis, i in enumerate(range(first, min(len(ms.rows), first + list_h))):
        n = ms.rows[i]
        y = list_top + vis
        base = curses.A_REVERSE if i == ms.cursor else curses.A_NORMAL

        sel = '»' if n.id in ms.selected else ' '
        op = ms.node_op(n)
        err = ms.row_error(n)
        if op:
            badge = op if op == '*' else OPS[op][0]
            battr = (pal.get('accent') if op == '*' else pal.get(OPS[op][1])) | curses.A_BOLD
        elif err:
            badge, battr = '✗', pal.get('error') | curses.A_BOLD
        else:
            badge, battr = ' ', curses.A_NORMAL

        marker = ('▾ ' if n.expanded else '▸ ') if n.expandable else '  '
        name = '  ' * n.depth + marker + n.label
        name_attr = base | (curses.A_BOLD if n.kind != UNIT else 0)
        if n.kind in (PROFILE, LINK):
            name_attr |= pal.get('accent')

        def col(c, s, attr, pad=True):
            x, cw = cols[c]
            _put(stdscr, y, x, (_fit(s, cw).ljust(cw) if pad else _fit(s, cw)), attr)

        _put(stdscr, y, 0, sel, pal.get('accent') | base | curses.A_BOLD)
        _put(stdscr, y, 1, badge, battr | base)
        col('name', name, name_attr)
        col('fam', n.driver, base | pal.get('dim'))
        col('scope', n.scope_str(), base | pal.get('accent' if _scope_is_choice(n) else 'dim'))
        st = n.status
        col('status', st, pal.get(STATUS_COLOR.get(st, 'dim')) | base)
        if err:
            ix = cols['inst'][0]
            _put(stdscr, y, ix, _fit(err, max(1, w - ix - 1)), base | pal.get('error'))
        else:
            col('inst', n.installed_str(), base | pal.get('dim'))
            col('latest', n.latest_str(), base | pal.get('dim'), pad=False)

    _put(stdscr, h - 6, 0, _fit(_methods_line(ms, ctx), w), pal.get('header'))
    info1, info2 = _infoblock(ms, ctx)
    _put(stdscr, h - 5, 0, _fit(info1, w), pal.get('accent'))
    _put(stdscr, h - 4, 0, _fit(info2, w), pal.get('dim'))

    status_line = f' selected:{len(ms.selected)}  staged:{len(ms.staged)}'
    if note:
        status_line += f'   {note}'
    nav = ' j/k move · g/G top/bottom · l/→ expand · h/← collapse · enter open · tab expand-all '
    act = ' space sel · a all · i/u/x inst/upg/rm · L lock · m method · c clear · X exec · ! issues · q quit '
    foot_attr = pal.get('dim') | curses.A_REVERSE
    _put(stdscr, h - 3, 0, _fit(status_line, w), pal.get('accent'))
    _put(stdscr, h - 2, 0, _fit(nav.ljust(w), w), foot_attr)
    _put(stdscr, h - 1, 0, _fit(act.ljust(w), w), foot_attr)
    stdscr.refresh()
    return diag_top


def _reload(ctx, old, dirty):
    '''Rebuild the menu after a pin change or an execute, requerying only `dirty` (+ any
    newly-appearing) units and REUSING the rest of the cached probe. Preserves cursor position,
    expansion, selection, and still-valid staged ops across the rebuild so the view stays put.
    Returns (ms, cfg, ledger, states, diags).'''
    cfg, _requested, _units, ledger, states = ctx.load_pipeline(reuse=old.states, dirty=dirty)
    ms = MenuState(states, _profile_comps(cfg))
    ids = {n.id for n in ms._all_nodes()}
    ms.selected = {i for i in old.selected if i in ids}
    ms.staged = {k: op for k, op in old.staged.items() if k in states}   # stale keys drop
    expanded = {n.id for n in old._all_nodes() if n.expandable and n.expanded}
    for n in ms._all_nodes():
        if n.expandable:
            n.expanded = n.id in expanded
    ms._refresh(keep_id=(old.cur().id if old.cur() else None))
    return ms, cfg, ledger, states, ctx.diagnostics(states)


def _scope_is_choice(node):
    '''True if the row's scope reflects a deliberate NON-DEFAULT choice — a scope-honoring driver
    installed at a scope other than its default (so it gets highlighted). Fixed-scope drivers
    (apt is always system, cargo always user) are NOT a choice and never highlight. For a group,
    true if any member qualifies.'''
    for m in node.members:
        honors, default = scope_meta(m.component.driver)
        if honors and m.scope and m.scope != default:
            return True
    return False


def _row_component(node):
    '''The profile-entry component name at a row, or None for a profile row. Node ids are
    `p:<profile>`, `c:<profile>:<name>` (a component / single-unit leaf) or
    `u:<profile>:<name>:<unit-key>` — the component name is the 3rd `:`-field.'''
    if node is None:
        return None
    parts = node.id.split(':')
    return parts[2] if parts[0] in ('c', 'u') and len(parts) >= 3 else None


def _popup_choose(stdscr, pal, title, options, start=0):
    '''A modal chooser drawn OVER the current screen (no drop to the terminal). `options` is a
    list of (label, tag-string). j/k or arrows move, enter selects, esc/q cancels. Returns the
    chosen index or None. The background stays put; the main loop redraws on return.'''
    h, w = stdscr.getmaxyx()
    n = len(options)
    inner = max([len(title)] + [len(lbl) + len(tag) + 2 for lbl, tag in options] + [24])
    box_w = min(inner + 4, max(20, w - 2))
    box_h = min(n + 4, max(5, h - 2))
    y0 = max(0, (h - box_h) // 2)
    x0 = max(0, (w - box_w) // 2)
    border = pal.get('accent') | curses.A_BOLD
    sel = start
    while True:
        _put(stdscr, y0, x0, '┌' + '─' * (box_w - 2) + '┐', border)
        _put(stdscr, y0, x0 + 2, f' {_fit(title, box_w - 4)} ', border)
        for r in range(1, box_h - 1):
            _put(stdscr, y0 + r, x0, '│' + ' ' * (box_w - 2) + '│', border)
        _put(stdscr, y0 + box_h - 1, x0, '└' + '─' * (box_w - 2) + '┘', border)
        for i, (label, tag) in enumerate(options):
            row = f'{label}'
            attr = curses.A_REVERSE if i == sel else curses.A_NORMAL
            _put(stdscr, y0 + 2 + i, x0 + 2, _fit(row.ljust(box_w - 4), box_w - 4), attr)
            if tag:
                _put(stdscr, y0 + 2 + i, x0 + box_w - 2 - len(tag), tag,
                     attr | pal.get('dim'))
        _put(stdscr, y0 + box_h - 1, x0 + 2, ' j/k · enter · esc ', border)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (27, ord('q')):
            return None
        if ch in (ord('j'), curses.KEY_DOWN):
            sel = min(n - 1, sel + 1)
        elif ch in (ord('k'), curses.KEY_UP):
            sel = max(0, sel - 1)
        elif ch in (ord('\n'), curses.KEY_ENTER, curses.KEY_RIGHT):
            return sel


def _apply_method_pin(ctx, name, via, already_pinned):
    '''Write a binding-pin name->via to the top config. Returns (changed, note, deferred): the
    footer note is immediate; the deferred message (promote hint) is printed on TUI exit.'''
    from .. import plugins
    if already_pinned:
        return False, f'{name} already uses {via}', None
    if ctx.runner.pretend:
        return False, f'[pretend] would pin {name} → {via}', None
    ctx.ensure_user_config()
    pins = plugins.read_pins(ctx.paths.user_config_file)
    pins[name] = via
    plugins.set_pins(ctx.paths.user_config_file, pins)
    hint = (f'pinned {name} → {via} (local); '
            f'run `configsys pin promote {name}` to make it portable via your primary plugin.')
    return True, f'pinned {name} → {via}', hint


def _pick_method(stdscr, pal, ms, ctx):
    '''Install-method picker for the current component: an in-place popup of its candidate methods;
    choosing one writes a binding-pin. Returns (changed, note, deferred). No drop to the terminal;
    the promote hint is deferred to TUI exit.'''
    name = _row_component(ms.cur())
    if not name:
        return False, 'pick a component row to choose its install method', None
    cands = ctx.routes.candidates(name)
    if len(cands) < 2:
        return False, f'{name}: only one install method available here', None
    options = []
    for c in cands:
        tag = ' '.join(t for t, on in (('default', c['default']), ('pinned', c['pinned'])) if on)
        when = f"  ({c['when']})" if c['when'] else ''
        options.append((f"via {c['via']}{when}", tag))
    start = next((i for i, c in enumerate(cands) if c['pinned'] or c['default']), 0)
    idx = _popup_choose(stdscr, pal, f'install method — {name}', options, start)
    if idx is None:
        return False, 'method unchanged', None
    chosen = cands[idx]
    return _apply_method_pin(ctx, name, chosen['via'], chosen['pinned'])


def _profile_comps(cfg):
    '''Per-profile component lists for the menu, attributed by DIRECT ownership so a base
    profile's components aren't repeated under every profile that `+includes` it. Each profile
    lists its own components (own = declared directly / via `+self` amendment, not via `+other`);
    a transitively-included component is dropped from an includer only when some active profile
    actually owns it (so it still shows there). A component nobody active owns stays visible under
    the includer — install stays transitive, so nothing is silently pulled without a menu row.'''
    actives = cfg.active_profiles
    own = {p: cfg.profile_own_components(p) for p in actives}
    owned_anywhere = set().union(*own.values()) if own else set()
    out = []
    for p in actives:
        ownset = set(own[p])
        names = [c for c in cfg.profile_components(p)          # keep full order
                 if c in ownset or c not in owned_anywhere]
        out.append((p, names))
    return out


def run(ctx):
    '''Entry point used by app.cmd_tui. Returns an exit code.'''
    cfg, _requested, _units, ledger, states = ctx.load_pipeline()
    ms = MenuState(states, _profile_comps(cfg))
    diags = ctx.diagnostics(states)

    with curses_screen() as stdscr:
        ctx.reporter.pause()          # curses owns the screen now; don't stream to stderr
        pal = Palette()
        note = ''
        show_diag = False
        diag_top = 0
        pending_report = None                     # a component whose op failed this session
        pending_notes = []                         # messages saved for after the TUI exits
        while True:
            diag_top = _draw(stdscr, pal, ms, ctx, note, diags, show_diag, diag_top)
            note = ''
            ch = stdscr.getch()

            if show_diag:                               # diagnostics page: scroll or exit
                if ch in (ord('!'), ord('q'), 27):
                    show_diag = False
                elif ch in (ord('j'), curses.KEY_DOWN):
                    diag_top += 1
                elif ch in (ord('k'), curses.KEY_UP):
                    diag_top = max(0, diag_top - 1)
                elif ch == ord('g'):
                    diag_top = 0
                elif ch == ord('G'):
                    diag_top = 10 ** 6                  # clamped by _draw
                continue

            if ch in (ord('q'), 27):
                break
            elif ch == ord('!'):
                if diags:
                    show_diag, diag_top = True, 0
            elif ch in (ord('j'), curses.KEY_DOWN):
                ms.move(1)
            elif ch in (ord('k'), curses.KEY_UP):
                ms.move(-1)
            elif ch == ord('g'):
                ms.top()
            elif ch == ord('G'):
                ms.bottom()
            elif ch in (ord('\n'), curses.KEY_ENTER):
                ms.enter()
            elif ch in (ord('l'), curses.KEY_RIGHT):
                ms.expand_or_jump()
            elif ch in (ord('h'), curses.KEY_LEFT):
                ms.collapse()
            elif ch == ord('L'):
                if not ms.toggle_lock():
                    note = 'nothing to lock/unlock here'
            elif ch == ord('\t'):
                ms.toggle_expand_all()
            elif ch == ord(' '):
                ms.toggle_select()
            elif ch == ord('a'):
                ms.select_all()
            elif ch == ord('c'):
                ms.unstage()
                ms.clear_selection()
                ms.errors.clear()
            elif ch == ord('m'):
                changed, note, deferred = _pick_method(stdscr, pal, ms, ctx)
                if deferred:
                    pending_notes.append(deferred)
                if changed:
                    ctx.invalidate()                       # re-read config so the new pin applies
                    try:
                        # partial requery: a pin change only alters the picked component's units,
                        # so reuse every cached state and re-probe just the new ones (dirty empty).
                        ms, cfg, ledger, states, diags = _reload(ctx, ms, set())
                    except Exception as e:  # noqa: BLE001 - surface, don't crash
                        note = f'reload failed: {e}'
            elif ch in KEY_TO_OP:
                if not ms.stage(KEY_TO_OP[ch]):
                    note = f'{KEY_TO_OP[ch]} not applicable here'
            elif ch == ord('X'):
                executed, note, outcomes = _confirm_and_execute(stdscr, pal, ms, ctx, ledger)
                curses.flushinp()  # drop keys typed during ops / the prompt
                if executed:
                    failed = {o.key: f'{o.op} failed: {o.detail}'
                              for o in outcomes if not o.ok}
                    bad = [o for o in outcomes if not o.ok]
                    if bad:                       # remember for a post-quit report nudge
                        pending_report = bad[-1].key.split('\\', 1)[-1]
                    try:
                        # partial requery: re-probe only the units the ops touched, reuse the rest
                        touched = {o.key for o in outcomes}
                        ms, cfg, ledger, states, diags = _reload(ctx, ms, touched)
                    except Exception as e:  # noqa: BLE001 - surface, don't crash
                        note = f'reload failed: {e}'
                    ms.staged.clear()          # the staged ops just ran; don't leave them badged
                    ms.errors = failed
                    curses.flushinp()  # ...and any typed during the re-inspect
    ctx.reporter.resume()             # back on the console (endwin has restored the terminal)
    ctx.report_session_summary(cfg, states, diags)   # -v+: leave a recap in the scrollback
    for msg in pending_notes:         # pin/promote hints held back so they don't interrupt the TUI
        print(f'configsys: {msg}')
    if pending_report:                # an op failed; its output is captured and persisted
        print(f'configsys: an op failed — run `configsys report {pending_report}` to file it '
              f'(OS + route + captured output; you approve the full text first).')
    return 0
