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
from ..errors import ConfigError
from ..osversion import clean_version
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
            v = clean_version(m.installed_version) or '—'   # strip v/epoch/revision so the
            return f'{v} [L]' if m.locked else v            # INSTALLED and LATEST columns line up
        present = sum(1 for m in self.members if m.present)
        return f'{present}/{len(self.members)}'

    def latest_str(self):
        if self.kind == UNIT:
            m = self.members[0]
            if not m.supported:
                return '?' if m.untrusted else ''
            return clean_version(m.latest_version) or '—'
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
    def __init__(self, states, layouts, transitive=None):
        '''`layouts` = [(profile, [item, ...])] for every profile to show as a top-level node;
        an item is a bare component name OR a ('component'|'include', name) tuple — an `include`
        renders as a LINK to the `p:<name>` profile node. `transitive` = {profile: [all transitive
        component names]} aggregates a profile's (and a link's) units; defaults to the layout's own
        component items (the direct-construction/test path, which has no includes).'''
        self.states = states               # {unit_key: ComponentState}
        self.layouts = [(p, [it if isinstance(it, tuple) else ('component', it) for it in items])
                        for p, items in layouts]
        self._name_units = self._invert()
        if transitive is None:
            transitive = {p: [name for kind, name in items if kind == 'component']
                          for p, items in self.layouts}
        self._profile_units = {p: self._units_for(names) for p, names in transitive.items()}
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

    def _units_for(self, names):
        keys = set()
        for name in names:
            keys.update(self._name_units.get(name, []))
        return sorted(keys)

    def _build_tree(self):
        roots = []
        for profile, items in self.layouts:
            pnode = Node(PROFILE, f'p:{profile}', profile, 0, [],
                         expandable=True, expanded=True)
            for kind, name in items:
                if kind == 'include':          # a link to the top-level p:<name> node
                    members = [self.states[k] for k in self._profile_units.get(name, [])
                               if k in self.states]
                    lnode = Node(LINK, f'l:{profile}:{name}', name, 1, members,
                                 link_target=f'p:{name}')
                    lnode.parent = pnode
                    pnode.children.append(lnode)
                    continue
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
                cnode.parent = pnode
                pnode.children.append(cnode)
            pnode.members = [self.states[k] for k in self._profile_units.get(profile, [])
                             if k in self.states]
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
        return None if node.kind in (PROFILE, LINK) else self.node_error(node)


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
        drv = get_driver(rc.driver, ctx.runner, ctx.paths)
        if drv is None:
            print(f'skip {key}: driver "{rc.driver}" not yet supported')
            outcomes.append(OpOutcome(op, key, rc.name, False, 'unsupported driver'))
            continue

        print(f'\n>>> {op} {key} (pkg: {rc.name})')
        if op == 'install':
            res = drv.install(rc)
        elif op == 'upgrade':
            res = drv.upgrade(rc)
        elif op == 'remove':
            res = drv.uninstall(rc)
        elif op == 'lock':
            res = drv.lock(rc)
            if res.ok:
                ledger.set_lock(key, True)
        elif op == 'unlock':
            res = drv.unlock(rc)
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
    DRIVER absorb the extra horizontal room; the two version columns (INSTALLED / LATEST) always
    get equal width. SCOPE/STATUS stay compact.'''
    start = 3                                     # after the select marker + op badge
    scope_w, status_w = 8, 9
    flex = max(24, (w - 1) - start - scope_w - status_w - 5)   # 5 inter-column gaps
    ver_w = max(8, min(24, flex // 4))            # INSTALLED == LATEST (roomier)
    rest = max(20, flex - 2 * ver_w)              # NAME + DRIVER share the remainder
    driver_w = max(7, min(rest // 4, 16))         # DRIVER: compact (driver names are short)
    name_w = max(14, rest - driver_w)                # NAME takes the rest
    nx = start
    fx = nx + name_w + 1
    scx = fx + driver_w + 1
    stx = scx + scope_w + 1
    ix = stx + status_w + 1
    lx = ix + ver_w + 1
    return {'name': (nx, name_w), 'driver': (fx, driver_w), 'scope': (scx, scope_w),
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
    parts += [f'installed: {clean_version(m.installed_version) or "—"}',
              f'latest: {clean_version(m.latest_version) or "—"}']
    if m.locked:
        parts.append('version-locked')
    drv = get_driver(rc.driver, ctx.runner, ctx.paths)
    loc = drv.location(rc) if drv is not None else None
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


def _fill_bg(stdscr, pal, h, w):
    '''Paint the diagonal gradient behind the whole screen, in constant-band segments per row.'''
    for y in range(h):
        x = 0
        while x < w:
            b = pal.band(y, x, h, w)
            x2 = x + 1
            while x2 < w and pal.band(y, x2, h, w) == b:
                x2 += 1
            width = x2 - x - (1 if (y == h - 1 and x2 == w) else 0)   # skip the corner cell
            if width > 0:
                try:
                    stdscr.addstr(y, x, ' ' * width, pal.fill(y, x, h, w))
                except curses.error:
                    pass
            x = x2


# -- screen router / nav bar ----------------------------------------------
SCREENS = [('1', 'components', 'Components'), ('2', 'profiles', 'Profiles'),
           ('3', 'plugins', 'Plugins'), ('4', 'dotfiles', 'Dotfiles'), ('5', 'config', 'Config')]
IMPLEMENTED = {'components', 'profiles', 'config'}
KEY_TO_SCREEN = {ord(k): sid for k, sid, _name in SCREENS}


def _draw_nav(stdscr, pal, screen, h, w):
    '''Row-0 chip bar: press a number to switch screens. Unbuilt screens are dimmed.'''
    x = 0
    for key, sid, name in SCREENS:
        chip = f' {key} {name} '
        elem = 'label' if sid == screen else ('menu_header' if sid in IMPLEMENTED else 'info_dim')
        _put(stdscr, 0, x, chip, pal.style(elem, 0, x, h, w))
        x += len(chip) + 1
    hint = ' ! issues · q quit '
    _put(stdscr, 0, max(x + 1, w - len(hint) - 1), _fit(hint, w - x), pal.style('footer', 0, x, h, w))


def _draw(stdscr, pal, ms, ctx, note, diags=(), show_diag=False, diag_top=0, screen='components'):
    if show_diag:
        return _draw_diagnostics(stdscr, pal, diags, diag_top)
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    cols = _columns(w)
    if pal.gradient:
        _fill_bg(stdscr, pal, h, w)

    _draw_nav(stdscr, pal, screen, h, w)
    # second line: the `configsys` chip, then the OS block (+ PRETEND) to its right, then the badge.
    title = ' configsys '
    _put(stdscr, 1, 0, title, pal.style('label', 1, 0, h, w))
    sub = f'  {ctx.os_info.block}'
    if ctx.runner.pretend:
        sub += '   [PRETEND]'
    _put(stdscr, 1, len(title), _fit(sub, max(1, w - len(title))), pal.style('os', 1, len(title), h, w))
    if diags:                                        # attention badge, right-aligned on the title line
        n = len(diags)
        elem = 'issue_error' if any(d['level'] == 'error' for d in diags) else 'issue_warning'
        badge = f' ⚠ {n} issue{"s" if n != 1 else ""} — press ! to view '
        bx = max(len(title) + len(sub) + 2, w - len(badge) - 1)
        _put(stdscr, 1, bx, _fit(badge, w - bx), pal.style(elem, 1, bx, h, w))

    for c, text in (('name', 'COMPONENT'), ('driver', 'DRIVER'), ('scope', 'SCOPE'),
                    ('status', 'STATUS'), ('inst', 'INSTALLED'), ('latest', 'LATEST')):
        x, cw = cols[c]
        _put(stdscr, 2, x, _fit(text, cw), pal.style('menu_header', 2, x, h, w))

    list_top = 3
    list_h = max(1, h - list_top - 6)  # methods + 2 infoblock + status + 2 footer lines
    ms.top = first = _scroll_top(ms.cursor, ms.top, list_h, len(ms.rows))

    _KIND_ELEM = {PROFILE: 'profile', LINK: 'link', COMPONENT: 'component', UNIT: 'unit'}
    for vis, i in enumerate(range(first, min(len(ms.rows), first + list_h))):
        n = ms.rows[i]
        y = list_top + vis
        sel = i == ms.cursor

        def col(c, s, element, pad=True):
            x, cw = cols[c]
            _put(stdscr, y, x, (_fit(s, cw).ljust(cw) if pad else _fit(s, cw)),
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

        if sel:                                      # solid highlight bar across the whole row
            _put(stdscr, y, 0, ' ' * (w - 1), pal.fill(y, 0, h, w, selected=True))
        _put(stdscr, y, 0, marker_sel, pal.style('select_marker', y, 0, h, w, selected=sel))
        _put(stdscr, y, 1, bch, pal.style(belem, y, 1, h, w, selected=sel))
        col('name', name, _KIND_ELEM.get(n.kind, 'unit'))
        col('driver', n.driver, 'driver')
        col('scope', n.scope_str(), 'scope_choice' if _scope_is_choice(n) else 'scope')
        col('status', n.status, n.status if n.status in STATUS_COLOR else 'unit')
        if err:
            ix = cols['inst'][0]
            _put(stdscr, y, ix, _fit(err, max(1, w - ix - 1)),
                 pal.style('row_error', y, ix, h, w, selected=sel))
        else:
            col('inst', n.installed_str(), 'version')
            col('latest', n.latest_str(), 'version', pad=False)

    _put(stdscr, h - 6, 0, _fit(_methods_line(ms, ctx), w), pal.style('methods', h - 6, 0, h, w))
    info1, info2 = _infoblock(ms, ctx)
    _put(stdscr, h - 5, 0, _fit(info1, w), pal.style('info', h - 5, 0, h, w))
    _put(stdscr, h - 4, 0, _fit(info2, w), pal.style('info_dim', h - 4, 0, h, w))

    status_line = f' selected:{len(ms.selected)}  staged:{len(ms.staged)}'
    if note:
        status_line += f'   {note}'
    nav = ' j/k move · g/G top/bottom · l/→ expand · h/← collapse · enter open · tab expand-all '
    act = ' space sel · a all · i/u/x inst/upg/rm · L lock · m method · c clear · X exec · ! issues · q quit '
    _put(stdscr, h - 3, 0, _fit(status_line, w), pal.style('status_line', h - 3, 0, h, w))
    _put(stdscr, h - 2, 0, _fit(nav.ljust(w), w), pal.style('footer', h - 2, 0, h, w))
    _put(stdscr, h - 1, 0, _fit(act.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
    stdscr.refresh()
    return diag_top


def _reload(ctx, old, dirty):
    '''Rebuild the menu after a pin change or an execute, requerying only `dirty` (+ any
    newly-appearing) units and REUSING the rest of the cached probe. Preserves cursor position,
    expansion, selection, and still-valid staged ops across the rebuild so the view stays put.
    Returns (ms, cfg, ledger, states, diags).'''
    cfg, _requested, _units, ledger, states = ctx.load_pipeline(reuse=old.states, dirty=dirty)
    layouts, transitive = _menu_model(cfg)
    ms = MenuState(states, layouts, transitive)
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
    # annotate each method with the version it would install (cached; the first open of a component
    # may briefly query native/discovery) + a "lags" flag vs the newest available, so the choice is
    # version-informed. Best-effort: a probe failure just omits versions.
    vers, tip = {}, None
    try:
        from .. import versionreport
        rep = versionreport.report(ctx, name)
        vers = {m.via: m for m in rep.methods}
        tip = rep.tip
    except Exception:  # noqa: BLE001 — never let a version probe block the picker
        pass
    # lay the labels out in columns — `via <name>` | version | (when) — so the versions line up
    # (the popup box auto-widens to the longest label). Compute the column widths first.
    rows = []
    for c in cands:
        mv = vers.get(c['via'])
        ver = clean_version(mv.latest if mv else None) or '—'   # normalized, like the columns
        tags = [t for t, on in (('default', c['default']), ('pinned', c['pinned'])) if on]
        if mv and mv.lags_tip:
            tags.append('lags')
        rows.append((c['via'], ver, f"({c['when']})" if c['when'] else '', ' '.join(tags)))
    via_w = max(len(via) for via, _v, _w, _t in rows)
    ver_w = max(len(v) for _via, v, _w, _t in rows)
    options = [(f"via {via:<{via_w}}   {ver:<{ver_w}}   {when}".rstrip(), tags)
               for via, ver, when, tags in rows]
    title = f'install method — {name}' + (f'   (tip {clean_version(tip)})' if tip else '')
    start = next((i for i, c in enumerate(cands) if c['pinned'] or c['default']), 0)
    idx = _popup_choose(stdscr, pal, title, options, start)
    if idx is None:
        return False, 'method unchanged', None
    chosen = cands[idx]
    return _apply_method_pin(ctx, name, chosen['via'], chosen['pinned'])


def _menu_model(cfg):
    '''(layouts, transitive) for the include-as-link menu. A `+other` include renders as a single
    LINK node (its own components live under the `other` profile, shown ONCE); expanding the link
    jumps to that profile. layouts covers every active profile AND every profile transitively
    referenced via +include (so each link has a top-level target). transitive gives each shown
    profile's full component set, for aggregating a profile/link's units.'''
    order = list(cfg.active_profiles)
    seen = set(order)
    layouts = {}
    i = 0
    while i < len(order):
        p = order[i]
        i += 1
        try:
            lay = cfg.profile_layout(p)
        except ConfigError:
            lay = []
        layouts[p] = lay
        for kind, ref in lay:
            if kind == 'include' and ref not in seen:
                seen.add(ref)
                order.append(ref)
    transitive = {}
    for p in order:
        try:
            transitive[p] = cfg.profile_components(p)
        except ConfigError:
            transitive[p] = []
    return [(p, layouts[p]) for p in order], transitive


SPLASH_THRESHOLD = 0.25    # only show the liquid fill if inspection is still going after this


def _splash_enabled(ctx):
    '''Whether the startup fill is ALLOWED (independent of the "is there work" timing gate). Off
    when: disabled via env, the user asked for verbose logging (they want the text log, not an
    animation), or a `theme: { splash: false }` opt-out. cmd_tui already guarantees a TTY.'''
    import os
    from .. import report
    if os.environ.get('CONFIGSYS_NO_SPLASH'):
        return False
    if ctx.reporter.level >= report.VERBOSE:
        return False
    s = (ctx.config.theme() or {}).get('splash')
    if s is False or s in ('false', 'no', 'off') or (isinstance(s, dict) and s.get('enabled') in (False, 'false', 'no')):
        return False
    return True


def _splash_forced():
    '''`CONFIGSYS_SPLASH=always` bypasses the "only when there's work" timing gate — the fill shows
    even on a fast/warm run (to preview it, or just enjoy it). CONFIGSYS_NO_SPLASH still wins.'''
    import os
    return os.environ.get('CONFIGSYS_SPLASH', '').lower() in ('always', 'force', '1')


class _InspectWorker:
    '''Runs load_pipeline on a background thread so the main thread can animate the splash while
    inspection proceeds. Exposes a live 0..1 progress fraction, a done flag, and re-raises any
    exception from the worker on join (so load errors still surface normally).'''

    def __init__(self, ctx):
        import threading
        self.ctx = ctx
        self._frac = 0.0
        self._i = 0
        self._total = 0
        self._done = threading.Event()
        self._result = None
        self._exc = None
        self._thread = threading.Thread(target=self._work, daemon=True)

    def _sink(self, i, total, *rest):
        self._i, self._total = i, total
        self._frac = (i / total) if total else 1.0

    def _work(self):
        try:
            self._result = self.ctx.load_pipeline(progress=self._sink)
        except BaseException as e:          # captured, re-raised on the main thread in join()
            self._exc = e
        finally:
            self._done.set()

    def start(self):
        self._thread.start()
        return self

    def wait_settled(self, timeout):
        '''Block up to `timeout`; return True if inspection is STILL running (→ show the splash).'''
        return not self._done.wait(timeout)

    def frac(self):
        return self._frac

    def counts(self):
        return (self._i, self._total)

    def done(self):
        return self._done.is_set()

    def join(self):
        self._done.wait()
        if self._exc is not None:
            raise self._exc
        return self._result


# -- F2 primitive: a bordered panel ---------------------------------------
def _panel(stdscr, pal, top, left, height, width, title, focused, h, w):
    '''Draw a bordered box; return (inner_top, inner_left, inner_h, inner_w) for its content.'''
    elem = 'menu_header' if focused else 'info_dim'
    bar = '─' * (width - 2)
    _put(stdscr, top, left, '┌' + bar + '┐', pal.style(elem, top, left, h, w))
    for r in range(top + 1, top + height - 1):
        _put(stdscr, r, left, '│', pal.style(elem, r, left, h, w))
        _put(stdscr, r, left + width - 1, '│', pal.style(elem, r, left + width - 1, h, w))
    _put(stdscr, top + height - 1, left, '└' + bar + '┘', pal.style(elem, top + height - 1, left, h, w))
    if title:
        te = 'label' if focused else 'menu_header'
        _put(stdscr, top, left + 2, _fit(f' {title} ', width - 4), pal.style(te, top, left + 2, h, w))
    return top + 1, left + 1, height - 2, width - 2


# -- Profiles screen ------------------------------------------------------
class ProfileScreen:
    '''Two-panel profile editor: profiles (left) + the full component catalog (right). A skin over
    configsys.actions — space toggles membership, `a` toggles a profile active.'''
    def __init__(self, ctx):
        self.ctx = ctx
        self.focus = 'left'          # 'left' = profiles, 'right' = catalog
        self.lcur = self.rcur = self.ltop = self.rtop = 0
        self.reload()

    def reload(self):
        cfg = self.ctx.config
        self.profiles = cfg.profile_names()
        self.active = set(cfg.active_profiles)
        self.catalog = sorted(self.ctx.routes.components)
        self._avail = {}
        self.lcur = min(self.lcur, max(0, len(self.profiles) - 1))
        self.rcur = min(self.rcur, max(0, len(self.catalog) - 1))

    def cur_profile(self):
        return self.profiles[self.lcur] if 0 <= self.lcur < len(self.profiles) else None

    def members(self, profile):
        try:
            return set(self.ctx.config.profile_components(profile)) if profile else set()
        except ConfigError:
            return set()

    def available(self, name):
        if name not in self._avail:
            try:
                self._avail[name] = bool(self.ctx.routes.candidates(name))
            except Exception:                       # noqa: BLE001 — unroutable -> grayed
                self._avail[name] = False
        return self._avail[name]


def _draw_profiles(stdscr, pal, ps, ctx, note, screen):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    if pal.gradient:
        _fill_bg(stdscr, pal, h, w)
    _draw_nav(stdscr, pal, screen, h, w)

    top, body_h = 1, h - 3
    lw = max(20, w // 3)
    rleft, rw = lw + 1, w - lw - 1
    prof = ps.cur_profile()
    members = ps.members(prof)

    # LEFT: profiles (full height)
    lit, lil, lih, liw = _panel(stdscr, pal, top, 0, body_h, lw, 'profiles',
                                ps.focus == 'left', h, w)
    ps.ltop = _scroll_top(ps.lcur, ps.ltop, lih, len(ps.profiles))
    for vis, i in enumerate(range(ps.ltop, min(len(ps.profiles), ps.ltop + lih))):
        name, y = ps.profiles[i], lit + vis
        sel = i == ps.lcur and ps.focus == 'left'
        if sel:
            _put(stdscr, y, lil, ' ' * liw, pal.fill(y, lil, h, w, selected=True))
        _put(stdscr, y, lil, _fit(f'{"●" if name in ps.active else "○"} {name}', liw),
             pal.style('profile', y, lil, h, w, selected=sel))

    # RIGHT TOP: detail for the highlighted component (names are esoteric) — description + methods
    cur = ps.catalog[ps.rcur] if ps.catalog and 0 <= ps.rcur < len(ps.catalog) else None
    desc_h = 7 if body_h >= 12 else 0
    if desc_h:
        dit, dil, dih, diw = _panel(stdscr, pal, top, rleft, desc_h, rw, 'component', False, h, w)
        if cur:
            comp = ctx.routes.components.get(cur)
            _put(stdscr, dit, dil, _fit(cur, diw), pal.style('label', dit, dil, h, w))
            desc = (comp.description if comp else '') or '(no description yet)'
            for k, line in enumerate(_wrap(desc, diw)[:dih - 2]):
                _put(stdscr, dit + 1 + k, dil, _fit(line, diw), pal.style('info', dit + 1 + k, dil, h, w))
            try:
                cands = ctx.routes.candidates(cur)
            except Exception:                       # noqa: BLE001
                cands = []
            mtext = ('methods: ' + '  '.join(c['via'] + ('*' if c['default'] else '') for c in cands)
                     if cands else 'methods: (not available on this OS)')
            _put(stdscr, dit + dih - 1, dil, _fit(mtext, diw),
                 pal.style('info_dim', dit + dih - 1, dil, h, w))

    # RIGHT BOTTOM: the component catalog
    ctop, cath = top + desc_h, body_h - desc_h
    rit, ril, rih, riw = _panel(stdscr, pal, ctop, rleft, cath, rw,
                                f'components — in "{prof}"' if prof else 'components',
                                ps.focus == 'right', h, w)
    ps.rtop = _scroll_top(ps.rcur, ps.rtop, rih, len(ps.catalog))
    for vis, i in enumerate(range(ps.rtop, min(len(ps.catalog), ps.rtop + rih))):
        name, y = ps.catalog[i], rit + vis
        sel = i == ps.rcur and ps.focus == 'right'
        elem = 'component' if ps.available(name) else 'info_dim'
        if sel:
            _put(stdscr, y, ril, ' ' * riw, pal.fill(y, ril, h, w, selected=True))
        _put(stdscr, y, ril, _fit(f'{"●" if name in members else " "} {name}', riw),
             pal.style(elem, y, ril, h, w, selected=sel))

    from .. import actions
    status = f' profile: {prof or "—"}    edits → {actions.edit_target(ctx)[1]}'
    if note:
        status += f'    {note}'
    navf = (' j/k move · h/l or tab focus · space toggle membership · a (de)activate profile'
            ' · 1-5 screens · q quit ')
    _put(stdscr, h - 2, 0, _fit(status, w), pal.style('status_line', h - 2, 0, h, w))
    _put(stdscr, h - 1, 0, _fit(navf.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
    stdscr.refresh()


# -- F2 primitive: a single-line text-input modal -------------------------
def _input_box(stdscr, pal, title, initial=''):
    '''Modal single-line text entry over the current screen. Returns the string on Enter, or None
    on Esc. Handles printable ASCII + backspace.'''
    h, w = stdscr.getmaxyx()
    box_w = min(max(len(title) + 4, 60), max(24, w - 2))
    box_h = 5
    y0, x0 = max(0, (h - box_h) // 2), max(0, (w - box_w) // 2)
    border = pal.get('accent') | curses.A_BOLD
    buf = list(initial)
    try:
        curses.curs_set(1)
    except curses.error:
        pass
    try:
        while True:
            _put(stdscr, y0, x0, '┌' + '─' * (box_w - 2) + '┐', border)
            _put(stdscr, y0, x0 + 2, f' {_fit(title, box_w - 4)} ', border)
            for r in range(1, box_h - 1):
                _put(stdscr, y0 + r, x0, '│' + ' ' * (box_w - 2) + '│', border)
            _put(stdscr, y0 + box_h - 1, x0, '└' + '─' * (box_w - 2) + '┘', border)
            _put(stdscr, y0 + box_h - 1, x0 + 2, ' enter · esc ', border)
            s = ''.join(buf)
            _put(stdscr, y0 + 2, x0 + 2, _fit(s, box_w - 4).ljust(box_w - 4), curses.A_UNDERLINE)
            try:
                stdscr.move(y0 + 2, x0 + 2 + min(len(s), box_w - 5))
            except curses.error:
                pass
            stdscr.refresh()
            ch = stdscr.getch()
            if ch == 27:
                return None
            if ch in (ord('\n'), curses.KEY_ENTER):
                return ''.join(buf)
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                if buf:
                    buf.pop()
            elif 32 <= ch < 127:
                buf.append(chr(ch))
    finally:
        try:
            curses.curs_set(0)
        except curses.error:
            pass


def _order_list(stdscr, pal, title, items):
    '''Reorder modal: j/k move the cursor; `space` grabs/drops the current item; while grabbed, j/k
    move THE ITEM up/down. Enter commits (returns the new order), Esc cancels (None).'''
    items = list(items)
    h, w = stdscr.getmaxyx()
    box_w = min(max(len(title) + 4, 46), max(24, w - 2))
    box_h = min(len(items) + 5, max(7, h - 2))
    y0, x0 = max(0, (h - box_h) // 2), max(0, (w - box_w) // 2)
    border = pal.get('accent') | curses.A_BOLD
    sel, grabbed = 0, False
    while True:
        _put(stdscr, y0, x0, '┌' + '─' * (box_w - 2) + '┐', border)
        _put(stdscr, y0, x0 + 2, f' {_fit(title, box_w - 4)} ', border)
        for r in range(1, box_h - 1):
            _put(stdscr, y0 + r, x0, '│' + ' ' * (box_w - 2) + '│', border)
        _put(stdscr, y0 + box_h - 1, x0, '└' + '─' * (box_w - 2) + '┘', border)
        _put(stdscr, y0 + box_h - 1, x0 + 2, ' space grab · j/k move · enter · esc ', border)
        for i, it in enumerate(items[:box_h - 4]):
            mark = '↕' if (grabbed and i == sel) else ('▸' if i == sel else ' ')
            attr = curses.A_REVERSE if i == sel else curses.A_NORMAL
            _put(stdscr, y0 + 2 + i, x0 + 2,
                 _fit(f'{i + 1:>2}. {mark} {it}'.ljust(box_w - 4), box_w - 4), attr)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch == 27:
            return None
        if ch in (ord('\n'), curses.KEY_ENTER):
            return items
        if ch == ord(' '):
            grabbed = not grabbed
        elif ch in (ord('j'), curses.KEY_DOWN):
            if grabbed and sel < len(items) - 1:
                items[sel], items[sel + 1] = items[sel + 1], items[sel]
                sel += 1
            elif not grabbed:
                sel = min(len(items) - 1, sel + 1)
        elif ch in (ord('k'), curses.KEY_UP):
            if grabbed and sel > 0:
                items[sel], items[sel - 1] = items[sel - 1], items[sel]
                sel -= 1
            elif not grabbed:
                sel = max(0, sel - 1)


def _setting_str(kind, val, key=None):
    if key == 'scope' and val in (None, ''):
        return 'user (default)'
    if kind == 'list':
        return ' '.join(val) if val else '(unset — built-in default)'
    if kind == 'bool':
        return 'true' if val else 'false'
    return str(val) if val not in (None, '') else '(unset)'


# -- Config screen --------------------------------------------------------
class ConfigScreen:
    '''Machine-settings form — a skin over configsys.actions.config_settings/set_config_setting.'''
    def __init__(self, ctx):
        self.ctx = ctx
        self.cur = 0
        self.reload()

    def reload(self):
        from .. import actions
        self.settings = actions.config_settings(self.ctx)
        self.keys = list(self.settings)
        self.cur = min(self.cur, max(0, len(self.keys) - 1))


def _draw_config(stdscr, pal, cs, ctx, note, screen):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    if pal.gradient:
        _fill_bg(stdscr, pal, h, w)
    _draw_nav(stdscr, pal, screen, h, w)
    it, il, ih, iw = _panel(stdscr, pal, 1, 0, h - 3, w, 'machine settings', True, h, w)
    y = it
    for i, key in enumerate(cs.keys):
        if y + 1 >= it + ih:
            break
        info = cs.settings[key]
        sel = i == cs.cur
        if sel:
            _put(stdscr, y, il, ' ' * iw, pal.fill(y, il, h, w, selected=True))
        _put(stdscr, y, il, _fit(f'{key:18} {_setting_str(info["kind"], info["value"], key)}', iw),
             pal.style('label' if sel else 'component', y, il, h, w, selected=sel))
        _put(stdscr, y + 1, il, _fit(f'   {info["desc"]}  (man: {info["man"]})', iw),
             pal.style('info_dim', y + 1, il, h, w))
        y += 3
    from .. import actions
    status = f' edits → {actions.edit_target(ctx)[1]}'
    if note:
        status += f'    {note}'
    navf = ' j/k move · enter/space edit · 1-5 screens · q quit '
    _put(stdscr, h - 2, 0, _fit(status, w), pal.style('status_line', h - 2, 0, h, w))
    _put(stdscr, h - 1, 0, _fit(navf.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
    stdscr.refresh()


def run(ctx):
    '''Entry point used by app.cmd_tui. Returns an exit code.'''
    # First-run config generation + the interactive primary-plugin offer must happen on the MAIN
    # thread, in the normal terminal, BEFORE the worker/curses — it prompts on stdin, which would
    # collide with the background load and curses init. load_pipeline's own call then no-ops.
    ctx.ensure_user_config(offer_primary=True)
    # Inspect on a worker thread; only paint the splash if it's still going after a short beat
    # ("only when there's work" — a warm/fast run skips straight to the menu), unless forced.
    worker = _InspectWorker(ctx).start()
    if not _splash_enabled(ctx):
        show_splash = False
    elif _splash_forced():
        show_splash = True                       # skip the timing gate entirely
    else:
        show_splash = worker.wait_settled(SPLASH_THRESHOLD)

    with curses_screen() as stdscr:
        ctx.reporter.pause()          # curses owns the screen now; don't stream to stderr
        pal = Palette(ctx.config.theme())
        if show_splash:
            import random
            from .splash import LiquidSplash
            LiquidSplash(stdscr, pal, random.Random(),
                         label='checking install state').play(
                             worker.done, worker.frac, worker.counts)
        cfg, _requested, _units, ledger, states = worker.join()   # re-raises load errors, if any
        layouts, transitive = _menu_model(cfg)
        ms = MenuState(states, layouts, transitive)
        diags = ctx.diagnostics(states)
        note = ''
        show_diag = False
        diag_top = 0
        screen = 'components'
        ps = None                                 # ProfileScreen, built lazily on first visit
        cs = None                                 # ConfigScreen, built lazily on first visit
        menu_dirty = False                        # a profile/config edit -> rebuild the Components tree
        pending_report = None                     # a component whose op failed this session
        pending_notes = []                         # messages saved for after the TUI exits
        while True:
            if show_diag:
                diag_top = _draw_diagnostics(stdscr, pal, diags, diag_top)
            elif screen == 'profiles':
                if ps is None:
                    ps = ProfileScreen(ctx)
                _draw_profiles(stdscr, pal, ps, ctx, note, screen)
            elif screen == 'config':
                if cs is None:
                    cs = ConfigScreen(ctx)
                _draw_config(stdscr, pal, cs, ctx, note, screen)
            else:
                diag_top = _draw(stdscr, pal, ms, ctx, note, diags, False, diag_top, screen)
            note = ''
            ch = stdscr.getch()

            if show_diag:                               # diagnostics overlay: scroll or exit
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

            # -- global keys (every screen) --
            if ch in (ord('q'), 27):
                break
            if ch == ord('!'):
                if diags:
                    show_diag, diag_top = True, 0
                continue
            if ch in KEY_TO_SCREEN:
                dest = KEY_TO_SCREEN[ch]
                if dest in IMPLEMENTED:
                    if dest == 'components' and menu_dirty:   # a profile edit changed membership
                        cfg = ctx.config                       # already invalidated by the edit
                        layouts, transitive = _menu_model(cfg)
                        ms = MenuState(states, layouts, transitive)   # states unchanged (config-only)
                        menu_dirty = False
                    screen = dest
                else:
                    note = f'the {dest} screen is not built yet'
                continue

            # -- Profiles screen --
            if screen == 'profiles':
                from .. import actions
                if ch in (ord('j'), curses.KEY_DOWN):
                    if ps.focus == 'left':
                        ps.lcur = min(len(ps.profiles) - 1, ps.lcur + 1)
                    else:
                        ps.rcur = min(len(ps.catalog) - 1, ps.rcur + 1)
                elif ch in (ord('k'), curses.KEY_UP):
                    if ps.focus == 'left':
                        ps.lcur = max(0, ps.lcur - 1)
                    else:
                        ps.rcur = max(0, ps.rcur - 1)
                elif ch == ord('\t'):
                    ps.focus = 'right' if ps.focus == 'left' else 'left'   # toggle
                elif ch in (ord('l'), curses.KEY_RIGHT):
                    ps.focus = 'right'
                elif ch in (ord('h'), curses.KEY_LEFT):
                    ps.focus = 'left'
                elif ch == ord('g'):
                    setattr(ps, 'lcur' if ps.focus == 'left' else 'rcur', 0)
                elif ch == ord('G'):
                    if ps.focus == 'left':
                        ps.lcur = max(0, len(ps.profiles) - 1)
                    else:
                        ps.rcur = max(0, len(ps.catalog) - 1)
                elif ch == ord('a') and ps.focus == 'left':
                    prof = ps.cur_profile()
                    if prof:
                        changed, _lbl = actions.set_profile_active(ctx, prof, prof not in ps.active)
                        ps.reload()
                        menu_dirty = menu_dirty or changed
                        note = (f'{prof} {"activated" if prof in ps.active else "deactivated"}'
                                if changed else 'no change')
                elif ch in (ord(' '), ord('\n'), curses.KEY_ENTER) and ps.focus == 'right':
                    prof = ps.cur_profile()
                    if prof and ps.catalog:
                        name = ps.catalog[ps.rcur]
                        act = 'remove' if name in ps.members(prof) else 'add'
                        try:
                            changed, _lbl = actions.set_profile_membership(ctx, prof, name, act)
                            ps.reload()
                            menu_dirty = menu_dirty or changed
                            note = (f'{name} {"added" if act == "add" else "removed"}'
                                    if changed else 'no change')
                        except Exception as e:  # noqa: BLE001 — surface, don't crash
                            note = f'edit failed: {e}'
                continue

            # -- Config screen --
            if screen == 'config':
                from .. import actions
                if ch in (ord('j'), curses.KEY_DOWN):
                    cs.cur = min(len(cs.keys) - 1, cs.cur + 1)
                elif ch in (ord('k'), curses.KEY_UP):
                    cs.cur = max(0, cs.cur - 1)
                elif ch == ord('g'):
                    cs.cur = 0
                elif ch == ord('G'):
                    cs.cur = max(0, len(cs.keys) - 1)
                elif ch in (ord(' '), ord('\n'), curses.KEY_ENTER):
                    key = cs.keys[cs.cur]
                    info = cs.settings[key]
                    try:
                        if info['kind'] == 'bool':
                            actions.set_config_setting(
                                ctx, key, ['false' if info['value'] else 'true'])
                            note = f'{key} = {"false" if info["value"] else "true"}'
                            cs.reload()
                            menu_dirty = True
                        elif info['kind'] == 'scalar':      # scope: user (default) / system / unset
                            cur_idx = {'user': 0, 'system': 1}.get(info['value'], 2)
                            idx = _popup_choose(stdscr, pal, key,
                                                [('user', '(default)'), ('system', ''),
                                                 ('unset', '(→ user)')], cur_idx)
                            if idx is not None:
                                actions.set_config_setting(ctx, key, [['user'], ['system'], []][idx])
                                note = f'{key} set'
                                cs.reload()
                                menu_dirty = True
                        elif key == 'driver-preference':    # ordered list -> reorder editor
                            from ..resolve import DEFAULT_DRIVER_PREFERENCE
                            cur = info['value'] or list(DEFAULT_DRIVER_PREFERENCE)
                            new = _order_list(stdscr, pal,
                                              'driver-preference — space grab, j/k move', cur)
                            if new is not None:
                                actions.set_config_setting(ctx, key, new)
                                note = f'{key} reordered'
                                cs.reload()
                                menu_dirty = True
                        else:                               # other list settings: input box
                            new = _input_box(stdscr, pal,
                                             f'{key}  (space-separated; empty clears)',
                                             ' '.join(info['value'] or []))
                            if new is not None:
                                actions.set_config_setting(ctx, key, new.split())
                                note = f'{key} set'
                                cs.reload()
                                menu_dirty = True
                    except Exception as e:  # noqa: BLE001 — surface, don't crash
                        note = f'edit failed: {e}'
                continue

            # -- Components screen --
            if ch in (ord('j'), curses.KEY_DOWN):
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
