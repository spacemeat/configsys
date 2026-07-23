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

from ..drivers import get_driver
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
    ord('L'): 'lock', ord('l'): 'unlock',
}

PROFILE, COMPONENT, UNIT = 'profile', 'component', 'unit'


class Node:
    def __init__(self, kind, id, label, depth, members, *, driver='',
                 expandable=False, expanded=False):
        self.kind = kind
        self.id = id
        self.label = label
        self.depth = depth
        self.members = members       # list[ComponentState] this node covers
        self.driver = driver
        self.expandable = expandable
        self.expanded = expanded
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
                return '—'
            v = m.installed_version or '—'
            return f'{v} [L]' if m.locked else v
        present = sum(1 for m in self.members if m.present)
        return f'{present}/{len(self.members)}'

    def latest_str(self):
        if self.kind == UNIT:
            m = self.members[0]
            return (m.latest_version or '—') if m.supported else ''
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
                        cnode.children.append(
                            Node(UNIT, f'u:{profile}:{name}:{m.key}', m.component.comp,
                                 2, [m], driver=m.component.driver))
                for m in members:
                    pmembers[m.key] = m
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

    def expand(self, want):
        n = self.cur()
        if n and n.expandable and n.expanded != want:
            n.expanded = want
            self._refresh(keep_id=n.id)

    def toggle_expand(self):
        n = self.cur()
        if n and n.expandable:
            self.expand(not n.expanded)

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


# -- execution ------------------------------------------------------------

class OpOutcome:
    def __init__(self, op, key, name, ok, detail=''):
        self.op = op
        self.key = key
        self.name = name
        self.ok = ok
        self.detail = detail


def execute_plan(ctx, plan, ledger):
    outcomes = []
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
        detail = '' if ok else (f'exit {res.returncode}' if res else 'no result')
        outcomes.append(OpOutcome(op, key, rc.name, ok, detail))

    ledger.save(ctx.paths)
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

# column start positions
NAME_X, FAM_X, SCOPE_X, STATUS_X, INST_X, LATEST_X = 3, 27, 39, 47, 58, 75


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
        return f' {rc.driver}\\{rc.comp}   ·   driver not yet supported', ''
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

    _put(stdscr, 0, 0, _fit(' configsys ', w),
         pal.get('title') | curses.A_BOLD | curses.A_REVERSE)
    sub = f'  {ctx.os_info.block}'
    if ctx.runner.pretend:
        sub += '   [PRETEND]'
    _put(stdscr, 1, 0, _fit(sub, w), pal.get('header'))
    if diags:                                        # attention badge, right-aligned on the sub line
        n = len(diags)
        lvl = 'error' if any(d['level'] == 'error' for d in diags) else 'outdated'
        badge = f'⚠ {n} issue{"s" if n != 1 else ""} — press ! to view '
        bx = max(len(sub) + 2, w - len(badge) - 1)
        _put(stdscr, 1, bx, _fit(badge, w - bx), pal.get(lvl) | curses.A_BOLD)

    hattr = pal.get('dim') | curses.A_BOLD
    _put(stdscr, 3, NAME_X, 'COMPONENT', hattr)
    _put(stdscr, 3, FAM_X, 'FAMILY', hattr)
    _put(stdscr, 3, SCOPE_X, 'SCOPE', hattr)
    _put(stdscr, 3, STATUS_X, 'STATUS', hattr)
    _put(stdscr, 3, INST_X, 'INSTALLED', hattr)
    _put(stdscr, 3, LATEST_X, 'LATEST', hattr)

    list_top = 4
    list_h = max(1, h - list_top - 5)  # 2 infoblock + status + 2 footer lines
    first = max(0, ms.cursor - list_h + 1) if ms.cursor >= list_h else 0

    for vis, i in enumerate(range(first, min(len(ms.rows), first + list_h))):
        n = ms.rows[i]
        y = list_top + vis
        base = curses.A_REVERSE if i == ms.cursor else curses.A_NORMAL

        sel = '»' if n.id in ms.selected else ' '
        op = ms.node_op(n)
        err = ms.node_error(n)
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
        if n.kind == PROFILE:
            name_attr |= pal.get('accent')

        _put(stdscr, y, 0, sel, pal.get('accent') | base | curses.A_BOLD)
        _put(stdscr, y, 1, badge, battr | base)
        _put(stdscr, y, NAME_X, _fit(name, FAM_X - NAME_X - 1).ljust(FAM_X - NAME_X - 1),
             name_attr)
        _put(stdscr, y, FAM_X, _fit(n.driver, SCOPE_X - FAM_X - 1).ljust(SCOPE_X - FAM_X - 1),
             base | pal.get('dim'))
        scope = n.scope_str()
        scope_attr = pal.get('accent' if scope == 'system' else 'dim')
        _put(stdscr, y, SCOPE_X, _fit(scope, STATUS_X - SCOPE_X - 1).ljust(STATUS_X - SCOPE_X - 1),
             base | scope_attr)

        st = n.status
        _put(stdscr, y, STATUS_X, _fit(st, INST_X - STATUS_X - 1).ljust(INST_X - STATUS_X - 1),
             pal.get(STATUS_COLOR.get(st, 'dim')) | base)

        if err:
            _put(stdscr, y, INST_X, _fit(err, max(1, w - INST_X - 1)),
                 base | pal.get('error'))
        else:
            _put(stdscr, y, INST_X,
                 _fit(n.installed_str(), LATEST_X - INST_X - 1).ljust(LATEST_X - INST_X - 1),
                 base | pal.get('dim'))
            _put(stdscr, y, LATEST_X, _fit(n.latest_str(), max(1, w - LATEST_X - 1)),
                 base | pal.get('dim'))

    info1, info2 = _infoblock(ms, ctx)
    _put(stdscr, h - 5, 0, _fit(info1, w), pal.get('accent'))
    _put(stdscr, h - 4, 0, _fit(info2, w), pal.get('dim'))

    status_line = f' selected:{len(ms.selected)}  staged:{len(ms.staged)}'
    if note:
        status_line += f'   {note}'
    nav = ' j/k move · g/G top/bottom · enter/→ expand · ← collapse · tab expand-all '
    act = ' space sel · a all · i/u/x inst/upg/rm · L/l lock · c clear · X exec · ! issues · q quit '
    foot_attr = pal.get('dim') | curses.A_REVERSE
    _put(stdscr, h - 3, 0, _fit(status_line, w), pal.get('accent'))
    _put(stdscr, h - 2, 0, _fit(nav.ljust(w), w), foot_attr)
    _put(stdscr, h - 1, 0, _fit(act.ljust(w), w), foot_attr)
    stdscr.refresh()
    return diag_top


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
            elif ch in (ord('\n'), curses.KEY_ENTER, curses.KEY_RIGHT):
                ms.toggle_expand() if ch != curses.KEY_RIGHT else ms.expand(True)
            elif ch == curses.KEY_LEFT:
                ms.expand(False)
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
            elif ch in KEY_TO_OP:
                if not ms.stage(KEY_TO_OP[ch]):
                    note = f'{KEY_TO_OP[ch]} not applicable here'
            elif ch == ord('X'):
                executed, note, outcomes = _confirm_and_execute(stdscr, pal, ms, ctx, ledger)
                curses.flushinp()  # drop keys typed during ops / the prompt
                if executed:
                    failed = {o.key: f'{o.op} failed: {o.detail}'
                              for o in outcomes if not o.ok}
                    try:
                        cfg, _requested, _units, ledger, states = ctx.load_pipeline()
                        ms = MenuState(states, _profile_comps(cfg))
                        diags = ctx.diagnostics(states)
                    except Exception as e:  # noqa: BLE001 - surface, don't crash
                        note = f'reload failed: {e}'
                    ms.errors = failed
                    curses.flushinp()  # ...and any typed during the re-inspect
    ctx.reporter.resume()             # back on the console (endwin has restored the terminal)
    return 0
