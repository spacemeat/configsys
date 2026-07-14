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

from ..families import get_family
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
    def __init__(self, kind, id, label, depth, members, *, family='',
                 expandable=False, expanded=False):
        self.kind = kind
        self.id = id
        self.label = label
        self.depth = depth
        self.members = members       # list[ComponentState] this node covers
        self.family = family
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

    def info(self):
        if self.kind == UNIT:
            m = self.members[0]
            if not m.supported:
                return '(family not yet supported)'
            if not m.present:
                return f'-> {m.latest_version or "?"}'
            if m.outdated:
                return f'{m.installed_version} -> {m.latest_version}'
            return m.installed_version or '-'
        present = sum(1 for m in self.members if m.present)
        return f'{present}/{len(self.members)} installed'


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
                                 family=m.component.family)
                else:
                    cnode = Node(COMPONENT, f'c:{profile}:{name}', name, 1, members,
                                 expandable=True, expanded=False)
                    for m in members:
                        cnode.children.append(
                            Node(UNIT, f'u:{profile}:{name}:{m.key}', m.component.comp,
                                 2, [m], family=m.component.family))
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
        fam = get_family(rc.family, ctx.runner, ctx.paths)
        if fam is None:
            print(f'skip {key}: family "{rc.family}" not yet supported')
            outcomes.append(OpOutcome(op, key, rc.name, False, 'unsupported family'))
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

FAM_X, STATUS_X, INFO_X = 33, 45, 57


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


def _draw(stdscr, pal, ms, ctx, note):
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    _put(stdscr, 0, 0, _fit(' configsys ', w),
         pal.get('title') | curses.A_BOLD | curses.A_REVERSE)
    sub = f'  {ctx.os_info.block}'
    if ctx.runner.pretend:
        sub += '   [PRETEND]'
    _put(stdscr, 1, 0, _fit(sub, w), pal.get('header'))

    header = f'   {"COMPONENT":28} {"FAMILY":11} {"STATUS":11} VERSION'
    _put(stdscr, 3, 0, _fit(header, w), pal.get('dim') | curses.A_BOLD)

    list_top = 4
    list_h = max(1, h - list_top - 2)
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
        _put(stdscr, y, 3, _fit(name, FAM_X - 4).ljust(FAM_X - 3), name_attr)
        _put(stdscr, y, FAM_X, _fit(n.family, 11).ljust(11), base | pal.get('dim'))

        st = n.status
        _put(stdscr, y, STATUS_X, _fit(st, 11).ljust(11),
             pal.get(STATUS_COLOR.get(st, 'dim')) | base)

        if err:
            info, iattr = err, base | pal.get('error')
        else:
            info = n.info()
            if n.locked:
                info += '  [locked]'
            iattr = base | pal.get('dim')
        _put(stdscr, y, INFO_X, _fit(info, max(1, w - INFO_X - 1)), iattr)

    status_line = f' selected:{len(ms.selected)}  staged:{len(ms.staged)}'
    if note:
        status_line += f'   {note}'
    foot = (' j/k move · enter/→ expand · ← collapse · tab all · space select · '
            'i/u/x inst/upg/rm · L/l lock · c clear · X exec · q quit ')
    _put(stdscr, h - 2, 0, _fit(status_line, w), pal.get('accent'))
    _put(stdscr, h - 1, 0, _fit(foot, w), pal.get('dim') | curses.A_REVERSE)
    stdscr.refresh()


def _profile_comps(cfg):
    return [(p, cfg.profile_components(p)) for p in cfg.active_profiles]


def run(ctx):
    '''Entry point used by app.cmd_tui. Returns an exit code.'''
    cfg, _requested, _units, ledger, states = ctx.load_pipeline()
    ms = MenuState(states, _profile_comps(cfg))

    with curses_screen() as stdscr:
        pal = Palette()
        note = ''
        while True:
            _draw(stdscr, pal, ms, ctx, note)
            note = ''
            ch = stdscr.getch()

            if ch in (ord('q'), 27):
                break
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
                if executed:
                    failed = {o.key: f'{o.op} failed: {o.detail}'
                              for o in outcomes if not o.ok}
                    try:
                        cfg, _requested, _units, ledger, states = ctx.load_pipeline()
                        ms = MenuState(states, _profile_comps(cfg))
                    except Exception as e:  # noqa: BLE001 - surface, don't crash
                        note = f'reload failed: {e}'
                    ms.errors = failed
    return 0
