'''menu.py — MenuState (pure interaction logic) + curses view + run loop.

MenuState holds rows, cursor, multi-selection, and staged operations, and enforces
which op is applicable to which component ("no surprises"). The curses layer only
renders it and translates keystrokes into MenuState calls. Executing the plan
suspends curses, runs each op through its family, then re-inspects.
'''

import curses

from ..families import get_family
from ..ledger import Ledger
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

def execute_plan(ctx, plan, ledger):
    for op, key, rc in plan:
        fam = get_family(rc.family, ctx.runner)
        if fam is None:
            print(f'skip {key}: family "{rc.family}" not supported')
            continue
        print(f'\n>>> {op} {key} (pkg: {rc.name})')
        if op == 'install':
            fam.install(rc)
        elif op == 'upgrade':
            fam.upgrade(rc)
        elif op == 'remove':
            fam.uninstall(rc)
        elif op == 'lock':
            if fam.lock(rc).ok:
                ledger.set_lock(key, True)
        elif op == 'unlock':
            if fam.unlock(rc).ok:
                ledger.set_lock(key, False)
    ledger.save(ctx.paths)


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
        badge = OPS[op][0] if op else ' '
        badge_attr = pal.get(OPS[op][1]) | curses.A_BOLD if op else curses.A_NORMAL

        _put(stdscr, y, 0, sel, pal.get('accent') | base | curses.A_BOLD)
        _put(stdscr, y, 1, badge, badge_attr | base)
        _put(stdscr, y, 2, ' ' + _fit(row.key, 30).ljust(31), base)

        status_attr = pal.get(STATUS_COLOR.get(s.status, 'dim')) | base
        _put(stdscr, y, 34, _fit(s.status, 12).ljust(12), status_attr)

        if s.status == 'unsupported':
            ver = '(family not yet supported)'
        elif not s.present:
            ver = f'-> {s.latest_version or "?"}'
        elif s.outdated:
            ver = f'{s.installed_version} -> {s.latest_version}'
        else:
            ver = s.installed_version or '-'
        if s.locked:
            ver += '  [locked]'
        _put(stdscr, y, 47, _fit(ver, max(1, w - 48)), base | pal.get('dim'))

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


def _confirm_and_execute(stdscr, pal, ms, ctx, ledger):
    plan = ms.plan()
    if not plan:
        return 'nothing staged'
    with suspended(stdscr):
        print('\nAbout to execute:')
        for op, key, rc in plan:
            print(f'  {op:8} {key}  (pkg: {rc.name})')
        try:
            ans = input('\nProceed? [y/N] ').strip().lower()
        except EOFError:
            ans = 'n'
        if ans == 'y':
            execute_plan(ctx, plan, ledger)
            input('\nDone. Press Enter to return...')
        else:
            print('cancelled.')
            input('Press Enter to return...')
    return 'executed' if ans == 'y' else 'cancelled'


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
            elif ch in KEY_TO_OP:
                if not ms.stage(KEY_TO_OP[ch]):
                    note = f'{KEY_TO_OP[ch]} not applicable here'
            elif ch in (ord('X'), ord('\n'), curses.KEY_ENTER):
                note = _confirm_and_execute(stdscr, pal, ms, ctx, ledger)
                if note == 'executed':
                    # re-inspect: state changed. Never let a reload error kill the
                    # session — keep the current view and report instead.
                    try:
                        ledger = Ledger.load(ctx.paths)
                        states = ctx.load_pipeline()[4]
                        ms = MenuState(states)
                    except Exception as e:  # noqa: BLE001 - surface, don't crash
                        note = f'reload failed: {e}'
    return 0
