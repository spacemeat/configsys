'''menu.py — MenuState (pure interaction logic) + curses view + run loop.

MenuState holds rows, cursor, multi-selection, and staged operations, and enforces
which op is applicable to which component ("no surprises"). The curses layer only
renders it and translates keystrokes into MenuState calls. Executing the plan
suspends curses, runs each op through its family, then re-inspects.
'''

import curses

from ..families import get_family
from ..ledger import Ledger
from ..planning import expand_plan
from .screen import curses_screen, suspended
from .theme import STATUS_COLOR, Palette

# op -> (single-char badge, palette color, predicate on ComponentState)
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


class Row:
    def __init__(self, key, state):
        self.key = key
        self.state = state


class MenuState:
    def __init__(self, states):
        self.rows = [Row(k, states[k]) for k in sorted(states)]
        self.cursor = 0
        self.selected = set()      # selected row indices
        self.staged = {}           # row index -> op name
        self.errors = {}           # unit key -> message from the last execute

    # -- navigation -------------------------------------------------------

    def move(self, delta):
        if not self.rows:
            return
        self.cursor = max(0, min(len(self.rows) - 1, self.cursor + delta))

    def top(self):
        self.cursor = 0

    def bottom(self):
        if self.rows:
            self.cursor = len(self.rows) - 1

    # -- selection --------------------------------------------------------

    def toggle_select(self):
        if not self.rows:
            return
        if self.cursor in self.selected:
            self.selected.discard(self.cursor)
        else:
            self.selected.add(self.cursor)

    def select_all(self):
        self.selected = set(range(len(self.rows)))

    def clear_selection(self):
        self.selected.clear()

    def _targets(self):
        return sorted(self.selected) if self.selected else (
            [self.cursor] if self.rows else [])

    # -- staging ----------------------------------------------------------

    def stage(self, op):
        pred = OPS[op][2]
        staged_any = False
        for i in self._targets():
            if pred(self.rows[i].state):
                self.staged[i] = op
                self.errors.pop(self.rows[i].key, None)  # re-attempting clears the mark
                staged_any = True
        return staged_any

    def unstage(self):
        for i in self._targets():
            self.staged.pop(i, None)

    def clear_all_staged(self):
        self.staged.clear()

    def plan(self):
        '''Ordered list of (op, key, ResolvedComponent) to execute.'''
        out = []
        for i in sorted(self.staged):
            row = self.rows[i]
            out.append((self.staged[i], row.key, row.state.component))
        return out


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
            print(f'skip {key}: family "{rc.family}" not supported')
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


# -- rendering ------------------------------------------------------------

def _fit(s, width):
    return s if len(s) <= width else s[:max(0, width - 1)] + '…'


def _put(stdscr, y, x, s, attr=0):
    '''addstr that never raises at the screen edge (esp. bottom-right cell).'''
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
    title = ' configsys '
    _put(stdscr, 0, 0, _fit(title, w), pal.get('title') | curses.A_BOLD | curses.A_REVERSE)
    sub = f'  OS {ctx.os_info.block}   profiles: {profiles}   units: {len(ms.rows)}'
    if ctx.runner.pretend:
        sub += '   [PRETEND]'
    _put(stdscr, 1, 0, _fit(sub, w), pal.get('header'))

    header = f'   {"COMPONENT":30} {"STATUS":12} VERSION'
    _put(stdscr, 3, 0, _fit(header, w), pal.get('dim') | curses.A_BOLD)

    list_top = 4
    list_h = max(1, h - list_top - 2)
    first = max(0, ms.cursor - list_h + 1) if ms.cursor >= list_h else 0

    for vis, i in enumerate(range(first, min(len(ms.rows), first + list_h))):
        row = ms.rows[i]
        s = row.state
        y = list_top + vis
        is_cursor = (i == ms.cursor)
        base = curses.A_REVERSE if is_cursor else curses.A_NORMAL

        sel = '»' if i in ms.selected else ' '
        op = ms.staged.get(i)
        err = ms.errors.get(row.key)
        if op:
            badge, badge_attr = OPS[op][0], pal.get(OPS[op][1]) | curses.A_BOLD
        elif err:
            badge, badge_attr = '✗', pal.get('error') | curses.A_BOLD
        else:
            badge, badge_attr = ' ', curses.A_NORMAL

        _put(stdscr, y, 0, sel, pal.get('accent') | base | curses.A_BOLD)
        _put(stdscr, y, 1, badge, badge_attr | base)
        _put(stdscr, y, 2, ' ' + _fit(row.key, 30).ljust(31), base)

        status_attr = pal.get(STATUS_COLOR.get(s.status, 'dim')) | base
        _put(stdscr, y, 34, _fit(s.status, 12).ljust(12), status_attr)

        if err:
            info, info_attr = err, base | pal.get('error')
        else:
            if s.status == 'unsupported':
                info = '(family not yet supported)'
            elif not s.present:
                info = f'-> {s.latest_version or "?"}'
            elif s.outdated:
                info = f'{s.installed_version} -> {s.latest_version}'
            else:
                info = s.installed_version or '-'
            if s.locked:
                info += '  [locked]'
            info_attr = base | pal.get('dim')
        _put(stdscr, y, 47, _fit(info, max(1, w - 48)), info_attr)

    n_staged = len(ms.staged)
    n_sel = len(ms.selected)
    foot = (' j/k move · space select · i/u/x install/upgrade/remove · '
            'L/l lock/unlock · c clear · a all · X execute · q quit ')
    status_line = f' selected:{n_sel}  staged:{n_staged}'
    if note:
        status_line += f'   {note}'
    _put(stdscr, h - 2, 0, _fit(status_line, w), pal.get('accent'))
    _put(stdscr, h - 1, 0, _fit(foot, w), pal.get('dim') | curses.A_REVERSE)
    stdscr.refresh()


def _summary_note(outcomes):
    n_ok = sum(1 for o in outcomes if o.ok)
    n_bad = len(outcomes) - n_ok
    if n_bad == 0:
        return f'{n_ok} ok'
    return f'{n_ok} ok, {n_bad} failed'


def _confirm_and_execute(stdscr, pal, ms, ctx, ledger):
    '''Returns (executed: bool, note: str, outcomes: list).'''
    raw = ms.plan()
    if not raw:
        return False, 'nothing staged', []
    units = {r.key: r.state.component for r in ms.rows}
    states = {r.key: r.state for r in ms.rows}
    plan = expand_plan(raw, units, states)
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


def run(ctx):
    '''Entry point used by app.cmd_tui. Returns an exit code.'''
    cfg, _requested, units, ledger, states = ctx.load_pipeline()
    ms = MenuState(states)

    with curses_screen() as stdscr:
        pal = Palette()
        note = ''
        while True:
            _draw(stdscr, pal, ms, ctx, cfg, note)
            note = ''
            ch = stdscr.getch()

            if ch in (ord('q'), 27):  # q / ESC
                break
            elif ch in (ord('j'), curses.KEY_DOWN):
                ms.move(1)
            elif ch in (ord('k'), curses.KEY_UP):
                ms.move(-1)
            elif ch == ord('g'):
                ms.top()
            elif ch == ord('G'):
                ms.bottom()
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
                    # re-inspect: state changed. Never let a reload error kill the
                    # session — keep the current view and report instead.
                    try:
                        ledger = Ledger.load(ctx.paths)
                        states = ctx.load_pipeline()[4]
                        ms = MenuState(states)
                    except Exception as e:  # noqa: BLE001 - surface, don't crash
                        note = f'reload failed: {e}'
                    ms.errors = failed  # mark rows that failed this run
    return 0
