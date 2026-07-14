'''menu.py — MenuState (pure interaction logic) + curses view + run loop.

Two presentations of the same resolved set, toggled with Tab:
  * top-level — one row per profile-entry name (e.g. `vulkan-dev`, `firefox`),
    aggregating the state of every unit it resolves to. Dependencies/parts (libxcb-*,
    apt\\flatpak, …) don't get their own row here.
  * full — one row per concrete unit (apt\\btop, flatpak\\firefox, apt\\libfuse2, …).

Staged operations are keyed by unit, so they survive a mode toggle: staging install
on the `vulkan-dev` group marks its parts, which show as staged in the full view too.
The curses layer only renders MenuState and turns keystrokes into calls to it.
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

GROUP, UNIT = 'group', 'unit'


class Row:
    '''A menu row over one or more unit states (a group aggregates several).'''

    def __init__(self, id, label, members, kind):
        self.id = id            # name (group) or unit key (unit)
        self.label = label
        self.members = members  # list[ComponentState]
        self.kind = kind

    @property
    def is_group(self):
        return self.kind == GROUP

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
        if self.is_group:
            present = sum(1 for m in self.members if m.present)
            return f'{present}/{len(self.members)} units installed'
        m = self.members[0]
        if not m.supported:
            return '(family not yet supported)'
        if not m.present:
            return f'-> {m.latest_version or "?"}'
        if m.outdated:
            return f'{m.installed_version} -> {m.latest_version}'
        return m.installed_version or '-'


class MenuState:
    def __init__(self, states, requested):
        self.states = states          # {unit_key: ComponentState}
        self.requested = requested     # {name: [profiles]}
        self._full = [Row(k, k, [states[k]], UNIT) for k in sorted(states)]
        self._top = self._build_groups()
        self.mode = 'top'
        self.rows = self._top
        self.cursor = 0
        self.selected = set()          # row ids in the current mode
        self.staged = {}               # unit_key -> op (mode-independent)
        self.errors = {}               # unit_key -> message

    def _build_groups(self):
        name_units = {}
        for key, st in self.states.items():
            for name in st.component.requested_as:
                name_units.setdefault(name, []).append(key)
        rows = []
        for name in sorted(name_units):
            members = [self.states[k] for k in sorted(name_units[name])]
            rows.append(Row(name, name, members, GROUP))
        return rows

    # -- mode -------------------------------------------------------------

    def toggle_mode(self):
        self.mode = 'full' if self.mode == 'top' else 'top'
        self.rows = self._full if self.mode == 'full' else self._top
        self.cursor = min(self.cursor, len(self.rows) - 1) if self.rows else 0
        self.selected.clear()

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
        self.selected = {r.id for r in self.rows}

    def clear_selection(self):
        self.selected.clear()

    def _target_rows(self):
        if self.selected:
            return [r for r in self.rows if r.id in self.selected]
        return [self.rows[self.cursor]] if self.rows else []

    # -- staging (unit-keyed) ---------------------------------------------

    def stage(self, op):
        pred = OPS[op][2]
        staged_any = False
        for row in self._target_rows():
            for m in row.members:
                if pred(m):
                    self.staged[m.key] = op
                    self.errors.pop(m.key, None)
                    staged_any = True
        return staged_any

    def unstage(self):
        for row in self._target_rows():
            for m in row.members:
                self.staged.pop(m.key, None)

    def clear_all_staged(self):
        self.staged.clear()

    def plan(self):
        return [(op, k, self.states[k].component) for k, op in sorted(self.staged.items())]

    # -- per-row badge/error (over the row's members) ---------------------

    def row_op(self, row):
        ops = {self.staged[m.key] for m in row.members if m.key in self.staged}
        if not ops:
            return None
        return next(iter(ops)) if len(ops) == 1 else '*'

    def row_error(self, row):
        for m in row.members:
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
    '''Run each staged op, returning an OpOutcome per op (ok + failure detail).'''
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
    '''Returns (executed: bool, note: str, outcomes: list).'''
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


def _draw(stdscr, pal, ms, ctx, cfg, note):
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    profiles = ', '.join(cfg.active_profiles)
    _put(stdscr, 0, 0, _fit(' configsys ', w),
         pal.get('title') | curses.A_BOLD | curses.A_REVERSE)
    sub = f'  {ctx.os_info.block}   profiles: {profiles}'
    if ctx.runner.pretend:
        sub += '   [PRETEND]'
    _put(stdscr, 1, 0, _fit(sub, w), pal.get('header'))

    view = 'top-level' if ms.mode == 'top' else 'full'
    other = 'full' if ms.mode == 'top' else 'top-level'
    _put(stdscr, 2, 0, _fit(f'  view: {view} ({len(ms.rows)})   ·   [tab] {other}', w),
         pal.get('accent'))

    header = f'   {"COMPONENT":30} {"STATUS":12} VERSION'
    _put(stdscr, 4, 0, _fit(header, w), pal.get('dim') | curses.A_BOLD)

    list_top = 5
    list_h = max(1, h - list_top - 2)
    first = max(0, ms.cursor - list_h + 1) if ms.cursor >= list_h else 0

    for vis, i in enumerate(range(first, min(len(ms.rows), first + list_h))):
        row = ms.rows[i]
        y = list_top + vis
        base = curses.A_REVERSE if i == ms.cursor else curses.A_NORMAL

        sel = '»' if row.id in ms.selected else ' '
        op = ms.row_op(row)
        err = ms.row_error(row)
        if op:
            badge, battr = (OPS[op][0] if op != '*' else '*'), (
                (pal.get(OPS[op][1]) if op != '*' else pal.get('accent')) | curses.A_BOLD)
        elif err:
            badge, battr = '✗', pal.get('error') | curses.A_BOLD
        else:
            badge, battr = ' ', curses.A_NORMAL

        label = ('▸ ' + row.label) if row.is_group else row.label
        _put(stdscr, y, 0, sel, pal.get('accent') | base | curses.A_BOLD)
        _put(stdscr, y, 1, badge, battr | base)
        _put(stdscr, y, 2, ' ' + _fit(label, 30).ljust(31),
             base | (curses.A_BOLD if row.is_group else 0))

        st = row.status
        _put(stdscr, y, 34, _fit(st, 12).ljust(12),
             pal.get(STATUS_COLOR.get(st, 'dim')) | base)

        if err:
            info, iattr = err, base | pal.get('error')
        else:
            info = row.info()
            if row.locked:
                info += '  [locked]'
            iattr = base | pal.get('dim')
        _put(stdscr, y, 47, _fit(info, max(1, w - 48)), iattr)

    n_staged = len(ms.staged)
    n_sel = len(ms.selected)
    status_line = f' selected:{n_sel}  staged:{n_staged}'
    if note:
        status_line += f'   {note}'
    foot = (' j/k move · tab top/full · space select · i/u/x inst/upg/rm · '
            'L/l lock · c clear · a all · X execute · q quit ')
    _put(stdscr, h - 2, 0, _fit(status_line, w), pal.get('accent'))
    _put(stdscr, h - 1, 0, _fit(foot, w), pal.get('dim') | curses.A_REVERSE)
    stdscr.refresh()


def run(ctx):
    '''Entry point used by app.cmd_tui. Returns an exit code.'''
    cfg, requested, _units, ledger, states = ctx.load_pipeline()
    ms = MenuState(states, requested)

    with curses_screen() as stdscr:
        pal = Palette()
        note = ''
        while True:
            _draw(stdscr, pal, ms, ctx, cfg, note)
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
            elif ch in (ord('\t'), ord('f')):
                ms.toggle_mode()
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
            elif ch in (ord('X'), ord('\n'), curses.KEY_ENTER):
                executed, note, outcomes = _confirm_and_execute(stdscr, pal, ms, ctx, ledger)
                if executed:
                    failed = {o.key: f'{o.op} failed: {o.detail}'
                              for o in outcomes if not o.ok}
                    mode = ms.mode
                    try:
                        cfg, requested, _units, ledger, states = ctx.load_pipeline()
                        ms = MenuState(states, requested)
                        if mode == 'full':
                            ms.toggle_mode()
                    except Exception as e:  # noqa: BLE001 - surface, don't crash
                        note = f'reload failed: {e}'
                    ms.errors = failed
    return 0
