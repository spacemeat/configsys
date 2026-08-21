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
import math
import threading
import time
from pathlib import Path

from .. import reportgen
from .. import shellguard
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

_REFRESH_WARN_DAYS = 30   # a package index older than this shows in warn-color on the Components header

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
        self.filter = ''                   # `F` substring filter over the tree (`/` is find)
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
        filt = getattr(self, 'filter', '').lower()

        def submatch(n):
            return filt in (n.label or '').lower() or any(submatch(c) for c in n.children)

        def walk(n):
            if filt:                                   # while filtering, show every branch that has a
                if not submatch(n):                    # match, expansion state ignored so it's visible
                    return
                out.append(n)
                for c in n.children:
                    walk(c)
            else:
                out.append(n)
                if n.expandable and n.expanded:
                    for c in n.children:
                        walk(c)
        for r in self.roots:
            walk(r)
        return out

    def set_filter(self, text):
        '''Set the substring filter over the tree (matches a row or any descendant) and rebuild the
        visible rows, keeping the cursor on the same node when it survives.'''
        self.filter = text
        keep = self.cur().id if self.cur() else None
        self._refresh(keep_id=keep)

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

    def go_top(self):                 # NB: not `top` — that would shadow the `self.top` scroll offset
        self.cursor = 0

    def go_bottom(self):
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
        staged_any = False
        for node in self._target_nodes():
            for m in node.members:
                # `i` (install) means "make it current": install if absent, else upgrade if
                # outdated. So one key covers both — a present-but-outdated unit stages an upgrade
                # instead of doing nothing. Other ops keep their own predicate.
                eff = op
                if op == 'install' and not OPS['install'][2](m) and OPS['upgrade'][2](m):
                    eff = 'upgrade'
                if OPS[eff][2](m):
                    self.staged[m.key] = eff
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
        # shell-writes guard: snapshot rc files before an installer op, revert + stage after (same
        # as the CLI path). Defensive re: a ctx without .config (test stubs) — arm() returns None.
        rc_snap = shellguard.arm(ctx.paths, getattr(ctx, 'config', None), rc.comp, op)
        try:
            try:
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
            finally:
                _guard_msg = shellguard.finish(ctx.paths, rc.comp, rc_snap)
                if _guard_msg:
                    print(f'  -> {_guard_msg}')
        except KeyboardInterrupt:          # Ctrl-C aborts the whole batch, back to the menu
            print(f'\n^C — aborted; {key} may be partially applied. Skipping the rest.')
            outcomes.append(OpOutcome(op, key, rc.name, False, 'interrupted (^C)'))
            break

        ok = bool(res and res.ok)
        detail = '' if ok else _fail_detail(res)
        if not ok and res is not None:
            last_failure = reportgen.failure_from_result(key, rc.driver, op, res)
        outcomes.append(OpOutcome(op, key, rc.name, ok, detail))

    ctx.runner.end_sudo()          # release the batch's sudo keep-alive (one prompt covered the run)
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
    ver_w = max(9, min(12, flex // 8))            # INSTALLED == LATEST — compact (clean_version'd)
    rest = max(20, flex - 2 * ver_w)              # NAME + DRIVER absorb the freed width
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


def _current_via(node, name):
    '''The via `name` ACTUALLY resolved to here — a pin, a detected-adopted method, or the auto-
    default — read off its resolved unit (`ResolvedComponent.via`), so it reflects the detection
    soft-pins that candidates() (routes-only) can't see. Matches the member whose component IS `name`
    (a component node also groups its transitive deps, whose vias are not ours). None when the row has
    no resolved unit on this machine.'''
    if node is None:
        return None
    for m in node.members:
        comp = getattr(m, 'component', None)
        if comp is not None and comp.comp == name and comp.via:
            return comp.via
    return None


def _method_tags(cands, current_via, default_via, choice, mark_unavailable=False):
    '''Render each candidate as a display tag. The CURRENT method (what installs now) is bracketed
    `[via]`; the auto-default is flagged `via *` ONLY when you're on something else (so an unmarked-
    but-not-bracketed list means "on the natural default", and a `*` elsewhere means "you've diverged"
    — the no-surprises signal, whether the divergence is a pin or a detected install). `~` marks a
    method not valid on this machine (Profiles' author-for-any-box view).'''
    out = []
    for c in cands:
        via = c['via']
        tag = f'[{via}]' if (choice and via == current_via) else via   # a lone method needs no marker
        if mark_unavailable and not c.get('available', True):
            tag += '~'
        if choice and via == default_via and via != current_via:
            tag += ' *'
        out.append(tag)
    return out


def _methods_line(ms, ctx):
    '''A line listing every install method eligible for the current component here — not just the
    default or the pin. The method that ACTUALLY resolves now (a pin, a detected-adopted install, or
    the auto-default) is bracketed `[via]`; when you're off the auto-default, that default is flagged
    `via *` (what unpinning would give you). Always names the method, even with one option. `m` opens
    the picker when there's a real choice (>=2).'''
    name = _row_component(ms.cur())
    if not name:
        return ''
    cands = ctx.routes.candidates(name)
    if not cands:
        return ''
    choice = len(cands) >= 2
    default_via = next((c['via'] for c in cands if c['default']), None)
    current_via = _current_via(ms.cur(), name) or default_via   # what installs now (detection-aware)
    parts = _method_tags(cands, current_via, default_via, choice)
    line = f' methods: {"   ".join(parts)}'
    if choice:                                               # surface the deciding rule (the "why")
        why = _why(ctx, name)
        line += f'      (default: {why} · m to change)' if why else '      (m to change)'
    return line


def _why(ctx, name):
    '''The rule that picked the default method for `name` here — most-specific `when:` / `standing:` /
    driver-preference / only method — for the ambient "why" hint. '' if undecidable/unroutable.'''
    from ..resolve import ResolveError, _select
    r = ctx.routes
    comp = r.components.get(name)
    if comp is None or not comp.bindings:
        return ''
    cx = r.cascade.context(r.block, r.version, r.cpu)
    try:
        return _select(comp, r.cascade, cx, r.pins, r.preference, r.candidate_only)[2]
    except ResolveError:
        return ''


def _edges_text(ctx, name):
    '''The capability edges for `name` — `requires:` / `provides:` with version floors — the graph
    the tree otherwise hides. Includes the requires declared on the binding that WINS here (e.g.
    blender-optix's `cuda-toolkit` is binding-level), so the edge shows regardless of where it's
    authored. No leading space (for embedding in the identity line); '' when it declares neither.'''
    comp = ctx.routes.components.get(name)
    if comp is None:
        return ''

    def fmt(names, versions):
        return ', '.join(f'{n} ({versions[n]})' if n in versions else n for n in names)

    req_names, reqs = list(comp.requires), dict(comp.req_versions)
    try:
        from ..resolve import ResolveError, _select, cap_constraints, cap_names
        r = ctx.routes
        cx = r.cascade.context(r.block, r.version, r.cpu)
        won = _select(comp, r.cascade, cx, r.pins, r.preference, r.candidate_only)[0]
        for cap in cap_names(won.details.get('requires')):
            if cap not in req_names:
                req_names.append(cap)
        reqs.update(cap_constraints(won.details.get('requires')))
    except ResolveError:
        pass
    parts = []
    if req_names:
        parts.append('requires: ' + fmt(req_names, reqs))
    if comp.provides:
        parts.append('provides: ' + fmt(comp.provides, comp.prov_versions))
    return '   ·   '.join(parts)


def _identity_line(ms, ctx, descriptions):
    '''The ambient identity+edges line for the current row: `name — description` followed by its
    capability edges. Folds the "where" graph into the EXISTING description slot — no extra row, so
    it never squeezes the component list (the cramping we wanted to avoid).'''
    name = _node_component(ms.cur())
    if not name:
        return ''
    desc = (descriptions or {}).get(name, '')
    parts = [f'{name} — {desc}' if desc else name]
    edges = _edges_text(ctx, name)
    if edges:
        parts.append(edges)
    return ' ' + '   ·   '.join(parts)


def _infoblock(ms, ctx):
    '''One detail line for the current row: versions / lock state, then the install location right
    after (the columns truncate these; here they show in full). Groups get a one-line summary.'''
    n = ms.cur()
    if n is None:
        return ''
    if n.kind != UNIT:
        return ' ' + n.summary()
    m = n.members[0]
    rc = m.component
    if not m.supported:
        # `error` carries the right message: the trust hint for untrusted, else "not supported"
        return f' {rc.driver}\\{rc.comp}   ·   {m.error or "driver not yet supported"}'
    parts = [f'{rc.driver}\\{rc.comp}']
    if m.scope:
        parts.append(f'scope: {m.scope}')
    parts += [f'installed: {clean_version(m.installed_version) or "—"}',
              f'latest: {clean_version(m.latest_version) or "—"}']
    if m.locked:
        parts.append('version-locked')
    drv = get_driver(rc.driver, ctx.runner, ctx.paths)
    loc = drv.location(rc) if drv is not None else None
    if loc:
        parts.append(f'at: {loc}')                # location now rides the same line as the versions
    if m.also_present:                            # coexisting installs via OTHER (unmanaged) methods
        parts.append('also present: ' + ', '.join(f'{via} {ver}' for via, _pkg, ver in m.also_present))
    return ' ' + '   ·   '.join(parts)


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


def _draw_where(stdscr, pal, lines, top, subject):
    '''The `w` full-page: the complete `configsys where` report for one component — every binding
    (valid / reachable / shadowed, the winner marked), the deciding rule, and the resolved dep tree.
    Scrollable, for the deep dive the ambient panel can't hold. Returns the clamped scroll top.'''
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    _put(stdscr, 0, 0, _fit(f' where — {subject} ', w),
         pal.get('title') | curses.A_BOLD | curses.A_REVERSE)
    body = []
    for ln in lines or ['(unknown component)']:
        low = ln.strip()
        if '<- default here' in ln or low.startswith('on '):
            attr = pal.get('installed') | curses.A_BOLD          # the winner / where it resolves
        elif low.startswith(('provides', 'requires', 'defined in', 'pinned')):
            attr = pal.get('accent')
        elif ln and not ln.startswith(' '):
            attr = pal.get('label') | curses.A_BOLD              # the component name header
        else:
            attr = pal.get('dim')
        body.append((ln, attr))
    body_h = max(1, h - 3)
    top = max(0, min(top, max(0, len(body) - body_h)))
    for i, (text, attr) in enumerate(body[top:top + body_h]):
        _put(stdscr, 2 + i, 0, _fit(text, w), attr)
    foot = ' j/k scroll · g/G top/bottom · w or q back '
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
           ('3', 'plugins', 'Plugins'), ('4', 'dotfiles', 'Dotfiles'), ('5', 'config', 'Config'),
           ('6', 'theme', 'Theme')]
IMPLEMENTED = {'components', 'profiles', 'plugins', 'dotfiles', 'config', 'theme'}
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
    descriptions = getattr(ms, 'descriptions', None) or {}   # {name -> desc}, cached per menu build
    pal.use_page(screen)
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
    rend = len(title) + len(sub)
    if screen == 'components':                       # package-index staleness, right of the OS tag
        from .. import refreshstate
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
            _put(stdscr, 1, rx, _fit(rtext, max(1, w - rx - 1)), pal.style(relem, 1, rx, h, w))
            rend = rx + len(rtext)
    if diags:                                        # attention badge, right-aligned on the title line
        n = len(diags)
        elem = 'issue_error' if any(d['level'] == 'error' for d in diags) else 'issue_warning'
        badge = f' ⚠ {n} issue{"s" if n != 1 else ""} — press ! to view '
        bx = max(rend + 2, w - len(badge) - 1)
        _put(stdscr, 1, bx, _fit(badge, w - bx), pal.style(elem, 1, bx, h, w))

    for c, text in (('name', 'COMPONENT'), ('driver', 'DRIVER'), ('scope', 'SCOPE'),
                    ('status', 'STATUS'), ('inst', 'INSTALLED'), ('latest', 'LATEST')):
        x, cw = cols[c]
        _put(stdscr, 2, x, _fit(text, cw), pal.style('menu_header', 2, x, h, w))

    list_top = 3
    list_h = max(1, h - list_top - 6)  # description + methods + infoblock + status + 2 footers
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
        nx, ncw = cols['name']
        _put(stdscr, y, nx, _fit(name, ncw).ljust(ncw),
             pal.style(_KIND_ELEM.get(n.kind, 'unit'), y, nx, h, w, selected=sel))
        rc = _node_component(n)                       # trail a faded description in the name slack
        rdesc = descriptions.get(rc, '') if rc else ''
        davail = ncw - len(name) - 2
        if rdesc and davail >= 6:
            _put(stdscr, y, nx + len(name) + 2, _fit(rdesc, davail),
                 pal.style('row_desc', y, nx + len(name) + 2, h, w, selected=sel))
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
    # vertical scroll indicator at the right edge (this list is full-width, no border box)
    _scrollbar_v(stdscr, pal, list_top, w - 1, list_h, ms.top, list_h, len(ms.rows), h, w)

    _put(stdscr, h - 6, 0, _fit(_identity_line(ms, ctx, descriptions), w),   # name — desc · requires/provides
         pal.style('info', h - 6, 0, h, w))
    _put(stdscr, h - 5, 0, _fit(_methods_line(ms, ctx), w), pal.style('methods', h - 5, 0, h, w))
    _put(stdscr, h - 4, 0, _fit(_infoblock(ms, ctx), w), pal.style('info_dim', h - 4, 0, h, w))

    status_line = f' selected:{len(ms.selected)}  staged:{len(ms.staged)}'
    if ms.filter:
        status_line += f'   filter:{ms.filter}'
    if note:
        status_line += f'   {note}'
    nav = ' j/k · g/G top/bottom · l/h expand/collapse · enter open · / find · F filter · tab expand-all '
    act = ' space sel · a all · i inst/upg · u upg · x rm · L lock · m change · w where · c clear · X exec · R refresh · ! issues · q quit '
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
    ms.descriptions = _describe(ctx)             # cache once; never hit ctx.routes per frame
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
    '''The component name at a row, or None for a profile row. A UNIT row's TRUE component comes from
    its member — a dependency unit is grouped under the component that requested it, so its id encodes
    the REQUESTER's name (`u:<profile>:<requester>:<unit-key>`), not its own. So an action on a
    dep row (e.g. `m`/`P` on cuda-toolkit-12 nested under blender) targets the dep, not the requester.
    Component-group / profile rows carry their own name in the id (`c:<profile>:<name>`).'''
    if node is None:
        return None
    if node.kind == UNIT and node.members:
        return node.members[0].component.comp
    parts = node.id.split(':')
    return parts[2] if parts[0] in ('c', 'u') and len(parts) >= 3 else None


def _node_component(node):
    '''The component name a row represents — its OWN, so a child unit under a group reports its own
    component (e.g. a gcc-13 part), not the parent's. A UNIT node carries the resolved component;
    a group / leaf falls back to the name in the node id.'''
    if node is None:
        return None
    if node.kind == UNIT and node.members:
        return node.members[0].component.comp
    return _row_component(node)


def _describe(ctx):
    '''{component name -> one-line description}, built ONCE per menu build. `ctx.routes` rebuilds a
    Resolver (re-parsing routes.hu) on EVERY access, so this must never be called per-row/per-frame
    — cache it on the MenuState and look up from the dict in the draw loop.'''
    try:
        return {name: c.description for name, c in ctx.routes.components.items()}
    except Exception:   # noqa: BLE001 — a resolve hiccup shouldn't blank the whole screen
        return {}


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
    '''Components-screen entry to the install-method picker: the current row's component.'''
    name = _row_component(ms.cur())
    if not name:
        return False, 'pick a component row to choose its install method', None
    return _pick_method_name(stdscr, pal, ctx, name)


def _pick_method_name(stdscr, pal, ctx, name):
    '''Install-method picker for component `name`: an in-place popup of its candidate methods;
    choosing one writes a binding-pin. Returns (changed, note, deferred). No drop to the terminal;
    the promote hint is deferred to TUI exit.'''
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


def _providers_of(routes, cap):
    '''Component names that declare `provides: cap` — a capability's candidate providers (the
    capability itself is not a component here, so it's not included).'''
    return sorted(n for n, c in routes.components.items()
                  if cap in getattr(c, 'provides', ()))


def _capability_choices(routes, name):
    '''Capabilities relevant to component `name` that have MORE THAN ONE provider — a real choice.
    Considers the caps it PROVIDES (so you repoint from a provider's row, e.g. stand on
    cuda-toolkit-12 to switch the `cuda-toolkit` capability to cuda-toolkit-11), the ones it REQUIRES
    at the component level, AND the requires declared on the binding that WINS here — so a variant
    whose SDK need rides its method (blender-optix's binding-level `cuda-toolkit`) still surfaces the
    provider choice from the component's own row. Returns [(cap, [providers])], deduped and sorted.'''
    comp = routes.components.get(name)
    if comp is None:
        return []
    caps = set(getattr(comp, 'provides', ())) | set(getattr(comp, 'requires', ()))
    try:                                                 # + the winning binding's requires (mirrors _edges_text)
        from ..resolve import ResolveError, _select, cap_names
        cx = routes.cascade.context(routes.block, routes.version, routes.cpu)
        won = _select(comp, routes.cascade, cx, routes.pins, routes.preference, routes.candidate_only)[0]
        caps.update(cap_names(won.details.get('requires')))
    except ResolveError:
        pass
    out = []
    for cap in sorted(caps):
        provs = _providers_of(routes, cap)
        if len(provs) >= 2:
            out.append((cap, provs))
    return out


def _apply_provider_pin(ctx, cap, provider, current):
    '''Write a provider-pin (capability `cap` -> component `provider`) to the top config — "whatever
    needs `cap`, use `provider`". Returns (changed, note, deferred); the promote hint is deferred.'''
    from .. import plugins
    if provider == current:
        return False, f'{cap} already provided by {provider}', None
    if ctx.runner.pretend:
        return False, f'[pretend] would set provider {cap} → {provider}', None
    ctx.ensure_user_config()
    pins = plugins.read_pins(ctx.paths.user_config_file)
    pins[cap] = provider
    plugins.set_pins(ctx.paths.user_config_file, pins)
    hint = (f'set provider {cap} → {provider} (local); '
            f'run `configsys pin promote {cap}` to make it portable via your primary plugin.')
    return True, f'{cap} now provided by {provider}', hint


def _pick_provider(stdscr, pal, ms, ctx):
    '''Components-screen entry: for the current row's component, choose which component PROVIDES a
    capability it's tied to (a provider-pin). The generic answer to "this capability has several
    providers — use that one instead" (e.g. the opt-in cuda-toolkit-11 vs default cuda-toolkit-12).
    Returns (changed, note, deferred).'''
    name = _row_component(ms.cur())
    if not name:
        return False, 'pick a component row to choose a provider', None
    choices = _capability_choices(ctx.routes, name)
    if not choices:
        return False, f'{name}: no capability with alternative providers here', None
    if len(choices) == 1:
        cap, provs = choices[0]
    else:                                                # more than one cap -> pick which first
        cidx = _popup_choose(stdscr, pal, f'capability — {name}',
                             [(c, f'{len(p)} providers') for c, p in choices], 0)
        if cidx is None:
            return False, 'provider unchanged', None
        cap, provs = choices[cidx]
    return _pick_provider_cap(stdscr, pal, ctx, name, cap, provs)


def _pick_provider_cap(stdscr, pal, ctx, name, cap, provs):
    '''Provider picker for ONE already-chosen capability `cap` (providers `provs`), from `name`'s row.
    Writes a provider-pin cap->provider. Split out of `_pick_provider` so the unified chooser, which
    has already picked the capability axis, can jump straight here. Returns (changed, note, deferred).'''
    routes = ctx.routes
    pins = ctx.config.pins()
    pinned = pins.get(cap)
    default = next((p for p in provs if not getattr(routes.components[p], 'opt_in', False)), None)
    # the provider in effect now: an explicit pin, else this row (if it provides cap), else the default
    current = pinned or (name if cap in getattr(routes.components.get(name), 'provides', ()) else default)
    avail, options = {}, []
    for p in provs:
        here = bool(routes.candidates(p))
        avail[p] = here
        tags = []
        if p == pinned:
            tags.append('pinned')
        elif p == current:
            tags.append('current')
        if not getattr(routes.components[p], 'opt_in', False):
            tags.append('default')
        if not here:
            tags.append('n/a here')
        options.append((p, ' '.join(tags)))
    start = (provs.index(pinned) if pinned in provs
             else provs.index(current) if current in provs else 0)
    idx = _popup_choose(stdscr, pal, f'provider for {cap}', options, start)
    if idx is None:
        return False, 'provider unchanged', None
    chosen = provs[idx]
    if not avail.get(chosen, True):
        return False, f'{chosen} has no install method on this machine — not set', None
    return _apply_provider_pin(ctx, cap, chosen, current)


def _pick_choices(stdscr, pal, ms, ctx):
    '''The unified "change how this resolves" chooser for the current row's component — one key that
    folds the install-method picker (a binding-pin) and the provider picker (a provider-pin). Lists
    only the axes this component actually has a choice on; a single axis opens its picker directly,
    several first ask which to change. Returns (changed, note, deferred).'''
    name = _row_component(ms.cur())
    if not name:
        return False, 'pick a component row to change how it resolves', None
    routes = ctx.routes
    axes = []                                            # (menu-label, kind, payload)
    if len(routes.candidates(name)) >= 2:
        axes.append((f'install method — {name}', 'method', None))
    for cap, provs in _capability_choices(routes, name):
        axes.append((f'provider for {cap}', 'provider', (cap, provs)))
    if not axes:
        return False, f'{name}: nothing to choose (one method, no multi-provider capability)', None
    if len(axes) == 1:
        _label, kind, payload = axes[0]                  # skip the menu when there's a single axis
    else:
        idx = _popup_choose(stdscr, pal, f'change — {name}', [(lbl, '') for lbl, _k, _p in axes], 0)
        if idx is None:
            return False, 'unchanged', None
        _label, kind, payload = axes[idx]
    if kind == 'method':
        return _pick_method_name(stdscr, pal, ctx, name)
    cap, provs = payload
    return _pick_provider_cap(stdscr, pal, ctx, name, cap, provs)


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


def _chosen_splash(ctx):
    '''(enabled, name): whether the startup splash is ALLOWED (independent of the "is there work"
    timing gate) and which provider was chosen — the `splash:` machine setting's value, or None for
    the built-in default. Off when: disabled via env, verbose logging (they want the text log), a
    `splash: off` setting, or the legacy `theme: { splash: false }` opt-out. TTY is guaranteed by
    cmd_tui. Whether a NAMED provider is actually registered is resolved at construction time.'''
    import os
    from .. import report
    if os.environ.get('CONFIGSYS_NO_SPLASH'):
        return False, None
    if ctx.reporter.level >= report.VERBOSE:
        return False, None
    v = ctx.config.splash()
    if isinstance(v, str) and v.lower() in ('false', 'no', 'off', '0'):
        return False, None
    if v is None:                                    # legacy: theme.splash false still disables
        s = (ctx.config.theme() or {}).get('splash')
        if s is False or s in ('false', 'no', 'off') or (isinstance(s, dict) and s.get('enabled') in (False, 'false', 'no')):
            return False, None
    name = None if (v is None or v.lower() in ('true', 'default', 'on')) else v
    if name is not None:                             # accept a plugin name as an alias for its splash
        from .. import plugins
        decls = plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
        name = plugins.resolve_splash_value(name, ctx.paths.plugins_dir, decls)
    return True, name


def _splash_forced(ctx):
    '''`CONFIGSYS_SPLASH=always` (or `--splash-linger`) bypasses the "only when there's work" timing
    gate — the fill shows even on a fast/warm run (to preview it, or just enjoy it). CONFIGSYS_NO_SPLASH
    still wins.'''
    return ctx.env.get('CONFIGSYS_SPLASH', '').lower() in ('always', 'force', '1', 'linger', 'hold')


def _splash_linger(ctx):
    '''`--splash-linger` / `CONFIGSYS_SPLASH=linger`: keep the splash animating AFTER inspection is
    done, until a key is pressed — so a too-fast load doesn't rob you of the show.'''
    return ctx.env.get('CONFIGSYS_SPLASH', '').lower() in ('linger', 'hold')


# The pre-inspect phases (load routes/config -> resolve -> detection) run BEFORE the per-unit inspect
# loop that drives real progress, so the bar would sit at 0% while they work. Reserve this share of the
# bar for them and EASE it up over ~_PRELUDE_TAU seconds, so the splash shows motion instead of a stall;
# the real per-unit progress then fills the remaining (1 - share).
_PRELUDE_SHARE = 0.35
_PRELUDE_TAU = 0.8       # seconds — ease time-constant (bar reaches ~63%/86%/95% of the share at 1/2/3τ)


class _InspectWorker:
    '''Runs load_pipeline on a background thread so the main thread can animate the splash while
    inspection proceeds. Exposes a live 0..1 progress fraction, a done flag, and re-raises any
    exception from the worker on join (so load errors still surface normally).'''

    def __init__(self, ctx):
        self.ctx = ctx
        self._i = 0
        self._total = 0
        self._start = time.monotonic()
        self._done = threading.Event()
        self._result = None
        self._exc = None
        self._thread = threading.Thread(target=self._work, daemon=True)

    def _sink(self, i, total, *rest):
        self._i, self._total = i, total

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
        if self._total:                          # inspecting: real per-unit progress, above the prelude
            return _PRELUDE_SHARE + (1 - _PRELUDE_SHARE) * (self._i / self._total)
        # pre-inspect: no per-unit signal yet — ease the bar UP toward the prelude share over ~its
        # duration, so the splash shows motion (not a stalled 0%) while routes load / resolve / detect.
        return _PRELUDE_SHARE * (1.0 - math.exp(-(time.monotonic() - self._start) / _PRELUDE_TAU))

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


def _thumb(span, offset, window, total):
    '''(pos, size) of a scrollbar thumb along a track of `span` cells, or None when everything fits.
    `window` items are visible starting at `offset` of `total`.'''
    if total <= window or span < 2:
        return None
    size = max(1, min(span, round(span * window / total)))
    maxoff = total - window
    pos = round((span - size) * offset / maxoff) if maxoff > 0 else 0
    return max(0, min(span - size, pos)), size


def _scrollbar_v(stdscr, pal, top, col, rows, offset, window, total, h, w):
    '''Overlay a vertical scrollbar on a panel's right border column: the track reuses the border,
    an accent thumb shows the visible fraction + position. No-op when it all fits.'''
    t = _thumb(rows, offset, window, total)
    if t is None:
        return
    pos, size = t
    for k in range(rows):
        on = pos <= k < pos + size
        _put(stdscr, top + k, col, '█' if on else '│',
             pal.style('select_marker' if on else 'info_dim', top + k, col, h, w))


def _scrollbar_h(stdscr, pal, row, left, cols, offset, window, total, h, w):
    '''Overlay a horizontal scrollbar on a panel's bottom border row (accent thumb over `─`).'''
    t = _thumb(cols, offset, window, total)
    if t is None:
        return
    pos, size = t
    for k in range(cols):
        on = pos <= k < pos + size
        _put(stdscr, row, left + k, '🬋' if on else '─',     # a vertically-centred bar, like the v-thumb
             pal.style('select_marker' if on else 'info_dim', row, left + k, h, w))


def _fuzzy_score(query, text):
    '''Score how well `text` fuzzy-matches `query` (case-insensitive); higher is better, None means
    no match. A contiguous substring beats a scattered subsequence; an earlier hit and a word-
    boundary start rank higher. Powers `/` find (jump the cursor to the best match).'''
    q = (query or '').lower()
    if not q:
        return None
    t = (text or '').lower()
    idx = t.find(q)
    if idx != -1:                                      # substring: the strongest kind of match
        boundary = idx == 0 or not t[idx - 1].isalnum()
        return 10000 - idx * 5 + (50 if boundary else 0)
    score, ti = 0, 0                                   # subsequence: every query char, in order
    for qc in q:
        nxt = t.find(qc, ti)
        if nxt == -1:
            return None
        score -= (nxt - ti)                            # penalize the gap skipped over
        ti = nxt + 1
    return score - ti                                  # a later finish is marginally worse


def _filter_edit(stdscr, initial, apply_fn, redraw):
    '''Live substring-FILTER entry (`F`): narrows the view to matching rows. Starts empty;
    `apply_fn(text)` sets the filter (called every keystroke so the view filters live) and
    `redraw()` repaints. Enter commits the typed text (empty text clears the filter); Esc — or
    backspace on an empty query — reverts to `initial`. A `filter:` prompt shows on the bottom line.
    Workflow: `Fgnuplot⏎` filters, `Fgod⎋` cancels, `F⌫` cancels, `F⏎` clears.'''
    buf = ''
    while True:
        apply_fn(buf)
        redraw()                                       # repaint with the live filter applied
        h, w = stdscr.getmaxyx()
        _put(stdscr, h - 1, 0, _fit(f' filter:{buf}▏', w).ljust(w), curses.A_REVERSE)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (10, 13, curses.KEY_ENTER):
            return buf                                 # commit (empty -> cleared)
        if ch == 27:                                   # Esc -> revert to the pre-filter state
            apply_fn(initial)
            return None
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            if not buf:                                # backspace on an empty query -> cancel too
                apply_fn(initial)
                return None
            buf = buf[:-1]
        elif 32 <= ch <= 126:
            buf += chr(ch)


def _find_next(labels, query, after):
    '''Index of the best fuzzy match for `query`, scanning from JUST AFTER `after` (wrapping). So
    among equally-good matches the next one after the cursor wins — repeated `/` with the same query
    steps sequentially through siblings (gcc-10..15, cudnn-8/9, python3.11/12/…). None = no match.'''
    best_i, best_s, n = None, None, len(labels)
    for off in range(n):
        i = (after + 1 + off) % n
        s = _fuzzy_score(query, labels[i])
        if s is not None and (best_s is None or s > best_s):
            best_i, best_s = i, s
    return best_i


def _find_edit(stdscr, labels, restore, set_cursor, redraw):
    '''Live fuzzy-FIND (`/`): as you type, jump the cursor to the best fuzzy match among `labels`
    (the visible items, index-aligned with the cursor). Unlike the old `/`, this does NOT filter —
    the list stays whole and only the cursor moves; type more to disambiguate. Enter keeps the
    cursor at the match; Esc — or backspace on an empty query — restores the `restore` index. A
    vim-style `/query` prompt shows on the bottom line.'''
    buf = ''

    def jump(b):
        i = _find_next(labels, b, restore)
        set_cursor(i if i is not None else restore)

    while True:
        jump(buf)                                      # empty query -> best_i None -> restore
        redraw()
        h, w = stdscr.getmaxyx()
        _put(stdscr, h - 1, 0, _fit(f' /{buf}▏', w).ljust(w), curses.A_REVERSE)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (10, 13, curses.KEY_ENTER):
            return                                     # commit — leave the cursor at the match
        if ch == 27:                                   # Esc -> restore the pre-find cursor
            set_cursor(restore)
            return
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            if not buf:
                set_cursor(restore)
                return
            buf = buf[:-1]
        elif 32 <= ch <= 126:
            buf += chr(ch)


# -- Profiles screen ------------------------------------------------------
# ---- attrs filter (Profiles catalog) — faceted include/exclude over component attribute tags ----
# Axes + vocabulary mirror docs/component-attrs.md. Used by the `A` filter modal + the catalog filter.
ATTR_AXES = [
    ('interface', ['CLI', 'TUI', 'GUI', 'daemon', 'web', 'headless']),
    ('role',      ['lib', 'SDK', 'app', 'toolchain', 'runtime', 'driver', 'font',
                   'theme', 'plugin', 'game', 'service', 'group', 'dotfiles']),
    ('license',   ['FOSS', 'FOSSish', 'proprietary', 'source-available', 'freeware',
                   'GNU', 'copyleft', 'permissive']),
    ('data',      ['tele', 'tele-optin', 'account', 'cloud', 'online', 'ads', 'paid', 'freemium']),
    ('pedigree',  ['electron', 'patent', 'legacy', 'beta']),
]
_ATTR_AXIS_OF = {t.lower(): axis for axis, tags in ATTR_AXES for t in tags}


def _attr_pass(tags, inc, exc):
    '''`tags` (a set of lowercased attrs) passes the faceted filter when it has NONE of the excluded
    tags AND, for every axis the user included a tag from, at least one of that axis's included tags
    (per-axis OR, cross-axis AND). Empty inc/exc -> everything passes.'''
    if exc & tags:
        return False
    if inc:
        for axis in {_ATTR_AXIS_OF.get(t) for t in inc}:
            if not ({t for t in inc if _ATTR_AXIS_OF.get(t) == axis} & tags):
                return False
    return True


def _attr_filter_modal(stdscr, pal, inc, exc):
    '''Tri-state faceted filter over the attr axes, drawn over the screen. space cycles a tag
    neutral(·) -> include(✓) -> exclude(✗) -> neutral; `c` clears all; enter applies; esc cancels.
    Returns (new_inc, new_exc) as lowercased sets, or None on cancel.'''
    rows = []                                       # ('head', axis) | ('tag', tag)
    for axis, tags in ATTR_AXES:
        rows.append(('head', axis))
        rows.extend(('tag', t) for t in tags)
    inc, exc = {x.lower() for x in inc}, {x.lower() for x in exc}
    sel = next((i for i, r in enumerate(rows) if r[0] == 'tag'), 0)
    top = 0
    border = pal.get('accent') | curses.A_BOLD
    while True:
        h, w = stdscr.getmaxyx()
        box_w = min(48, max(30, w - 4))
        vis = max(3, min(len(rows), h - 6))
        box_h = vis + 4
        y0, x0 = max(0, (h - box_h) // 2), max(0, (w - box_w) // 2)
        top = min(sel, top) if sel < top else (sel - vis + 1 if sel >= top + vis else top)
        _put(stdscr, y0, x0, '┌' + '─' * (box_w - 2) + '┐', border)
        _put(stdscr, y0, x0 + 2, ' filter catalog by attributes ', border)
        for r in range(1, box_h - 1):
            _put(stdscr, y0 + r, x0, '│' + ' ' * (box_w - 2) + '│', border)
        _put(stdscr, y0 + box_h - 1, x0, '└' + '─' * (box_w - 2) + '┘', border)
        _put(stdscr, y0 + box_h - 1, x0 + 2, ' space:·/✓/✗ · c:clear · enter · esc ', border)
        for k in range(vis):
            idx = top + k
            if idx >= len(rows):
                break
            kind, val = rows[idx]
            yy = y0 + 1 + k
            if kind == 'head':
                _put(stdscr, yy, x0 + 2, _fit(val, box_w - 4), pal.get('dim') | curses.A_BOLD)
            else:
                mark = '✓' if val.lower() in inc else ('✗' if val.lower() in exc else '·')
                attr = curses.A_REVERSE if idx == sel else curses.A_NORMAL
                _put(stdscr, yy, x0 + 2, _fit(f'  [{mark}] {val}'.ljust(box_w - 4), box_w - 4), attr)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (27, ord('q')):
            return None
        if ch in (ord('\n'), curses.KEY_ENTER):
            return inc, exc
        if ch in (ord('j'), curses.KEY_DOWN):               # land only on tag rows (skip axis headers)
            sel = next((i for i in range(sel + 1, len(rows)) if rows[i][0] == 'tag'), sel)
        elif ch in (ord('k'), curses.KEY_UP):
            sel = next((i for i in range(sel - 1, -1, -1) if rows[i][0] == 'tag'), sel)
        elif ch == ord('c'):
            inc.clear()
            exc.clear()
        elif ch == ord(' ') and rows[sel][0] == 'tag':
            t = rows[sel][1].lower()
            if t in inc:                            # ✓ -> ✗
                inc.discard(t)
                exc.add(t)
            elif t in exc:                          # ✗ -> ·
                exc.discard(t)
            else:                                   # · -> ✓
                inc.add(t)


class ProfileScreen:
    '''Two-panel profile editor: profiles (left) + the full component catalog (right). A skin over
    configsys.actions — space toggles membership, `a` toggles a profile active.'''
    def __init__(self, ctx):
        self.ctx = ctx
        self.focus = 'left'          # 'left' = profiles, 'right' = catalog
        self.lcur = self.rcur = self.ltop = self.rtop = 0
        self.rcol_left = 0           # leftmost visible catalog column (grid horizontal scroll)
        self.rrows, self.rncols = 1, 1   # grid dims, set each draw; the key handler moves by column
        self.pfilter = self.cfilter = ''   # substring filters for the profiles / catalog panes
        self.expanded = set()            # node keys of expanded profiles (inline `+include` tree)
        self.starred = set()             # profile NAMES starred (▸) — their OWN members filter the catalog
        self.attr_inc = set()            # `A` faceted attr filter: lowercased tags to INCLUDE
        self.attr_exc = {'dotfiles'}     # ...and to EXCLUDE — hide the -dotfiles companions by default
        self.show_removed = False        # `~`: within the star-filter, also reveal a starred profile's
                                         #      ~-pruned components (marked `~`) — the clone-and-prune view
        self._res = {}                   # component -> (available, via, pinned); survives reloads
        self.reload()

    # -- profiles tree (top-level profiles + inline `+include` children) --
    def visible_pnodes(self):
        '''Flattened visible tree: [(name, depth, key, expandable, expanded)]. Top-level profiles
        (filtered by pfilter) with each expanded profile's `+includes` shown indented beneath it
        (cycle-guarded). `key` is the ancestor path, so the same profile expands independently under
        different parents.'''
        f = self.pfilter.lower()
        roots = [p for p in self.profiles if f in p.lower()] if f else self.profiles
        out = []

        def walk(name, depth, path):
            key = '\x00'.join(path + [name])
            kids = [c for c in sorted(self.ctx.config.profile_includes(name))
                    if c not in path and c != name and c in self._profset]
            expandable = bool(kids)
            expanded = expandable and key in self.expanded
            out.append((name, depth, key, expandable, expanded))
            if expanded:
                for c in kids:
                    walk(c, depth + 1, path + [name])
        for r in roots:
            walk(r, 0, [])
        return out

    def cur_node(self):
        v = self.visible_pnodes()
        return v[self.lcur] if 0 <= self.lcur < len(v) else None

    def expand_cur(self):
        nd = self.cur_node()
        if nd and nd[3] and not nd[4]:               # expandable and collapsed
            self.expanded.add(nd[2])
            return True
        return False

    def collapse_cur(self):
        v = self.visible_pnodes()
        if not (0 <= self.lcur < len(v)):
            return
        name, depth, key, expandable, expanded = v[self.lcur]
        if expanded:
            self.expanded.discard(key)
        elif depth > 0:                              # a child -> jump to its parent row
            for j in range(self.lcur - 1, -1, -1):
                if v[j][1] == depth - 1:
                    self.lcur = j
                    break

    def _include_closure(self, name):
        '''A profile plus every profile it transitively `+include`s (cycle-guarded). Starring the
        whole chain makes the base's members visible, and a derived profile's `~`-pruned components
        (which the base still lists) then render with the `~` marker — the clone-and-prune view.'''
        seen, stack = set(), [name]
        while stack:
            p = stack.pop()
            if p in seen:
                continue
            seen.add(p)
            try:
                stack.extend(self.ctx.config.profile_includes(p))
            except Exception:                        # noqa: BLE001 — a bad include contributes nothing
                pass
        return seen & self._profset                  # real profiles only

    def toggle_star(self):
        nd = self.cur_node()
        if nd:
            clan = self._include_closure(nd[0])      # the profile + everything it inherits
            if nd[0] in self.starred:
                self.starred -= clan                 # unstar the whole chain
            else:
                self.starred |= clan                 # star the profile AND its inherited profiles
            self.rcur, self.rcol_left = 0, 0         # catalog membership changed -> reset its cursor

    def _starred_members(self):
        if not self.starred:
            return None
        m = set()
        for p in self.starred:
            try:                                     # a starred profile's OWN (directly-declared)
                m |= set(self.ctx.config.profile_own_components(p))   # members — NOT its +include'd ones
            except Exception:                        # noqa: BLE001 — a bad profile just contributes nothing
                pass
        return m

    def _starred_removed(self):
        '''Union of ~-pruned components across the starred profiles — what a `~term` dropped, so it
        isn't a member. Revealed (marked `~`) inside the star filter when `show_removed` is on.'''
        m = set()
        for p in self.starred:
            try:
                m |= set(self.ctx.config.profile_removed(p))
            except Exception:                        # noqa: BLE001 — a bad profile contributes nothing
                pass
        return m

    def vcatalog(self):
        f = self.cfilter.lower()
        cat = [c for c in self.catalog if f in c.lower()] if f else self.catalog
        sm = self._starred_members()                 # `*` star filter: starred profiles' OWN members
        if sm is not None:
            allowed = sm | (self._starred_removed() if self.show_removed else set())
            cat = [c for c in cat if c in allowed]
        if self.attr_inc or self.attr_exc:           # `A` attrs filter (faceted include/exclude)
            comps = self.ctx.routes.components
            cat = [c for c in cat if _attr_pass(
                {a.lower() for a in getattr(comps.get(c), 'attrs', [])}, self.attr_inc, self.attr_exc)]
        return cat

    def attr_summary(self):
        '''Short `✓a ✗b` chip for the catalog title, or '' at the pristine default (only the
        implicit `-dotfiles` hide, which the nav hint already advertises).'''
        parts = ['✓' + t for t in sorted(self.attr_inc)] + ['✗' + t for t in sorted(self.attr_exc)]
        if parts == ['✗dotfiles']:
            return ''
        return '  ' + ' '.join(parts) if parts else ''

    def set_pfilter(self, text):
        self.pfilter = text
        self.lcur = min(self.lcur, max(0, len(self.visible_pnodes()) - 1))

    def set_cfilter(self, text):
        self.cfilter = text
        self.rcur = min(self.rcur, max(0, len(self.vcatalog()) - 1))
        self.rcol_left = 0

    def reload(self):
        cfg = self.ctx.config
        self.profiles = cfg.profile_names()
        self._profset = set(self.profiles)
        self.starred &= self._profset                # drop stars for profiles that no longer exist
        self.active = set(cfg.active_profiles)
        # profiles reached transitively via `+include` from an active one, but not themselves in
        # `configs:` — marked ◐ (indirectly active) vs ● (directly active) vs ○ (inactive).
        ind, stack = set(), list(self.active)
        while stack:
            for inc in cfg.profile_includes(stack.pop()):
                if inc not in self.active and inc not in ind:
                    ind.add(inc)
                    stack.append(inc)
        self.active_indirect = ind
        self.catalog = sorted(self.ctx.routes.components)
        # KEEP self._res: a membership / profile edit doesn't change how a component RESOLVES (its
        # via), so re-resolving the whole visible set (~17ms each) on every toggle was the ~1.5s lag.
        # The method picker (`m`) is the only edit that changes resolution; it drops its own entry.
        self.lcur = min(self.lcur, max(0, len(self.visible_pnodes()) - 1))
        self.rcur = min(self.rcur, max(0, len(self.vcatalog()) - 1))
        self._warm_cache()               # resolving each component is ~17ms; warm off-thread so
                                         # scrolling the catalog isn't sluggish the first time through

    def _warm_cache(self):
        '''Populate _resolve for the whole catalog on a daemon thread. The menu loop blocks in
        getch() (GIL released) while idle, so this fills within a few seconds of opening the screen
        without stuttering the UI. A generation guard makes a later reload() abandon this sweep.'''
        if all(nm in self._res for nm in self.catalog):
            return                                   # already warm (the cache survives reloads)
        self._warm_gen = getattr(self, '_warm_gen', 0) + 1
        gen, catalog = self._warm_gen, list(self.catalog)

        def run():
            for name in catalog:
                if self._warm_gen != gen:            # a reload superseded us — stop
                    return
                try:
                    self._resolve(name)
                except Exception:                    # noqa: BLE001 — never let warming crash
                    pass
        threading.Thread(target=run, daemon=True).start()

    def cur_profile(self):
        nd = self.cur_node()
        return nd[0] if nd else None

    def members(self, profile):
        try:
            return set(self.ctx.config.profile_components(profile)) if profile else set()
        except ConfigError:
            return set()

    def own_members(self, profile):
        '''Components the profile declares as its OWN (direct/self-amend, not via a +other include).'''
        try:
            return set(self.ctx.config.profile_own_components(profile)) if profile else set()
        except ConfigError:
            return set()

    def removed_members(self, profile):
        '''Components a `~term` removes from the profile (for the `~` marker).'''
        return self.ctx.config.profile_removed(profile) if profile else set()

    def _resolve(self, name):
        '''(available, resolved_via, pinned) for a component — cached. The resolved via is the
        method it installs with now (the pin, else the preference-picked default); `pinned` is set
        when a binding-pin chose it. One candidates() call feeds both the grey-out and the method.'''
        if name not in self._res:
            try:
                cands = self.ctx.routes.candidates(name)
            except Exception:                       # noqa: BLE001 — unroutable
                cands = []
            win = next((c for c in cands if c['default']), None)
            self._res[name] = (bool(cands), win['via'] if win else None, bool(win and win['pinned']))
        return self._res[name]

    def available(self, name):
        return self._resolve(name)[0]

    def method(self, name):
        '''(resolved_via, pinned) for the row's method label.'''
        _avail, via, pinned = self._resolve(name)
        return via, pinned


def _draw_profiles(stdscr, pal, ps, ctx, note, screen):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    pal.use_page(screen)
    if pal.gradient:
        _fill_bg(stdscr, pal, h, w)
    _draw_nav(stdscr, pal, screen, h, w)

    top, body_h = 1, h - 4                           # status + legend row, then TWO nav rows below
    lw = max(16, w // 6)                             # profiles pane: narrow, leaving the grid room
    rleft, rw = lw + 1, w - lw - 1
    prof = ps.cur_profile()
    members = ps.members(prof)
    own = ps.own_members(prof)                       # direct (●) vs via-include (↳)
    removed = ps.removed_members(prof)               # ~term drops (~) for the selected profile
    if ps.show_removed:                              # ...plus the starred profiles' drops the filter reveals
        removed = removed | ps._starred_removed()
    # row-tint backgrounds derived from the theme's selection colour: a dimmer bar marks the current
    # row of the UNFOCUSED pane (so the profile stays visible while you navigate components), and a
    # subtle tint marks the components that are members of the selected profile.
    _sel = pal.sel_bg_rgb
    residual_bg = tuple(round(_sel[i] * 0.55) for i in range(3))
    member_bg = tuple(round(_sel[i] * 0.28) for i in range(3))
    low_color = not pal.have256    # 8/16-colour has no room for a dim tint -> those quantize to black
                                   # (invisible); reverse-video the unfocused-current row instead.

    # LEFT: profiles as a tree — top-level + inline `+include` children; ▸ marks a starred profile
    vnodes = ps.visible_pnodes()
    ltitle = 'profiles' + (f'  filter:{ps.pfilter}' if ps.pfilter else '') + (f'  ▸{len(ps.starred)}' if ps.starred else '')
    lit, lil, lih, liw = _panel(stdscr, pal, top, 0, body_h, lw, ltitle,
                                ps.focus == 'left', h, w)
    ps.ltop = _scroll_top(ps.lcur, ps.ltop, lih, len(vnodes))
    for vis, i in enumerate(range(ps.ltop, min(len(vnodes), ps.ltop + lih))):
        name, depth, key, expandable, expanded = vnodes[i]
        y = lit + vis
        cur = i == ps.lcur
        foc = cur and ps.focus == 'left'
        rbg = residual_bg if (cur and not foc) else None   # dimmer bar for the current row unfocused
        rev = curses.A_REVERSE if (low_color and rbg is not None) else 0
        if foc:
            _put(stdscr, y, lil, ' ' * liw, pal.fill(y, lil, h, w, selected=True))
        elif rbg is not None:
            _put(stdscr, y, lil, ' ' * liw,
                 curses.A_REVERSE if low_color else pal.fill(y, lil, h, w, bg=rbg))
        star = '▸' if name in ps.starred else ' '     # selection is the bar; ▸ now means "starred"
        exp = '▾' if expanded else ('▹' if expandable else ' ')
        act = '●' if name in ps.active else ('◐' if name in ps.active_indirect else '○')
        row = f'{star}{"  " * depth}{exp}{act} {name}'
        _put(stdscr, y, lil, _fit(row, liw),
             pal.style('profile', y, lil, h, w, selected=foc, bg=(None if low_color else rbg)) | rev)
    _scrollbar_v(stdscr, pal, lit, lw - 1, lih, ps.ltop, lih, len(vnodes), h, w)

    # RIGHT TOP: detail for the highlighted component (names are esoteric) — description + methods
    vcat = ps.vcatalog()
    cur = vcat[ps.rcur] if vcat and 0 <= ps.rcur < len(vcat) else None
    # the component NAME rides the panel title, so the box is short (2 desc lines + a "required by"
    # line + an "in profiles" line) and the catalog grid below gets the reclaimed rows.
    desc_h = 7 if body_h >= 12 else 0
    if desc_h:
        dit, dil, dih, diw = _panel(stdscr, pal, top, rleft, desc_h, rw, cur or 'component', False, h, w)
        if cur:
            comp = ctx.routes.components.get(cur)
            desc = (comp.description if comp else '') or '(no description yet)'
            for k, line in enumerate(_wrap(desc, diw)[:dih - 3]):
                _put(stdscr, dit + k, dil, _fit(line, diw), pal.style('info', dit + k, dil, h, w))
            # attribute tags (kind filter, orthogonal to profiles): a tag active in the `A` filter
            # is marked ✓ (included) / ✗ (excluded) so you can see why a component shows or hides.
            atags = getattr(comp, 'attrs', []) if comp else []
            if atags:
                shown = [(('✓' if a.lower() in ps.attr_inc else '✗' if a.lower() in ps.attr_exc else '')
                          + a) for a in atags]
                atext = 'attrs: ' + ' '.join(shown)
            else:
                atext = 'attrs: (untagged)'
            _put(stdscr, dit + dih - 3, dil, _fit(atext, diw),
                 pal.style('method_dim', dit + dih - 3, dil, h, w))
            # What DEPENDS ON this component — every other component (and DRIVER, marked ⎈) that names
            # a capability it provides in its requires/suggests/parts, across ALL install methods
            # (machine-agnostic: we're authoring profiles, not installing). Distinct from "in profiles".
            try:
                deps = ctx.routes.dependents(cur)
            except Exception:                       # noqa: BLE001 — never let the detail box break the screen
                deps = []
            if deps:
                names = [(f'⎈ {n}' if is_drv else n) for n, is_drv in deps]
                dtext = 'required by: ' + ', '.join(names)
            else:
                dtext = 'required by: (none)'
            _put(stdscr, dit + dih - 2, dil, _fit(dtext, diw),
                 pal.style('dependents', dit + dih - 2, dil, h, w))
            # Which profiles contain this component — ● direct owners (declared as their own), then ↳
            # indirect (pulled in only via a `+other` include). The useful context while authoring
            # profiles (install methods are a machine concern, out of place on this screen).
            try:
                direct, indirect = ctx.config.profiles_containing(cur)
            except Exception:                       # noqa: BLE001 — never let the detail box break the screen
                direct, indirect = [], []
            if direct or indirect:
                tags = ['● ' + p for p in direct] + ['↳ ' + p for p in indirect]
                ptext = 'in profiles: ' + ' '.join(tags)
            else:
                ptext = 'in profiles: (none)'
            _put(stdscr, dit + dih - 1, dil, _fit(ptext, diw),
                 pal.style('method_dim', dit + dih - 1, dil, h, w))

    # RIGHT BOTTOM: the component catalog (filtered), as a COLUMN-MAJOR grid filling the pane width
    ctop, cath = top + desc_h, body_h - desc_h
    ctitle = ((f'components — in "{prof}"' if prof else 'components')
              + (f'  filter:{ps.cfilter}' if ps.cfilter else '')
              + (f'  ▸{",".join(sorted(ps.starred))}' if ps.starred else '')
              + ('  +~removed' if ps.show_removed and ps.starred else '')
              + ps.attr_summary())
    rit, ril, rih, riw = _panel(stdscr, pal, ctop, rleft, cath, rw, ctitle, ps.focus == 'right', h, w)
    n = len(vcat)
    rows = max(1, rih)                               # each column is as tall as the pane
    # size columns from the FULL catalog's longest NAME (stable) so a filter that narrows to short
    # names doesn't shrink the columns; the draw keeps the name readable and truncates a long method.
    longest = max((len(nm) for nm in ps.catalog), default=12)
    col_w = max(1, min(riw, max(20, min(34, longest + 10))))  # `▸● name  method`
    ncols = max(1, riw // col_w) if riw > 0 else 1
    col_w = riw // ncols if ncols else riw           # redistribute to fill the width exactly
    total_cols = (n + rows - 1) // rows
    ps.rrows, ps.rncols = rows, ncols                # let the key handler move by column
    cur_col = ps.rcur // rows
    if cur_col < ps.rcol_left:                       # keep the cursor's column in view
        ps.rcol_left = cur_col
    elif cur_col >= ps.rcol_left + ncols:
        ps.rcol_left = cur_col - ncols + 1
    ps.rcol_left = max(0, min(ps.rcol_left, max(0, total_cols - ncols)))
    for vc in range(ncols if riw > 0 else 0):
        col = ps.rcol_left + vc
        if col >= total_cols:
            break
        cx = ril + vc * col_w
        for rr in range(rows):
            i = col * rows + rr
            if i >= n:
                break
            name, y = vcat[i], rit + rr
            cur = i == ps.rcur
            foc = cur and ps.focus == 'right'
            avail, via, pinned = ps._resolve(name)
            elem = 'component' if avail else 'info_dim'
            cell = col_w - 1
            # background: focused cursor (bright, wins) > current-but-unfocused (residual) > member
            if foc:
                rbg = None                           # the selection bar overrides the member tint
            elif cur:
                rbg = residual_bg
            elif name in members:
                rbg = member_bg
            else:
                rbg = None
            # 8/16-colour: the dim tints vanish -> reverse the unfocused-current row so it stays
            # visible; a member's subtle tint just drops (it's secondary to the cursor).
            rev = curses.A_REVERSE if (low_color and cur and not foc) else 0
            tint = None if low_color else rbg
            if foc:
                _put(stdscr, y, cx, ' ' * cell, pal.fill(y, cx, h, w, selected=True))
            elif rev:
                _put(stdscr, y, cx, ' ' * cell, curses.A_REVERSE)
            elif tint is not None:
                _put(stdscr, y, cx, ' ' * cell, pal.fill(y, cx, h, w, bg=tint))
            cm = '▸' if cur else ' '
            mk = ('●' if name in own else '↳') if name in members else ('~' if name in removed else ' ')
            # the resolved method trails the name, in the muted method colour; a pin is marked `[via]`
            mstr = (f'[{via}]' if pinned else via) if via else ''
            nm_txt = f'{cm}{mk} {name}'
            # the NAME has priority: it keeps its full width; the method gets whatever room is left
            # after it (right-aligned, truncated if long), and is dropped when there's < 3 cols left.
            m_room = cell - len(nm_txt) - 1
            if mstr and m_room >= 3:
                mshow = _fit(mstr, m_room)
                _put(stdscr, y, cx, _fit(nm_txt, cell - len(mshow) - 1),
                     pal.style(elem, y, cx, h, w, selected=foc, bg=tint) | rev)
                mx = cx + cell - len(mshow)
                _put(stdscr, y, mx, mshow, pal.style('method_dim', y, mx, h, w, selected=foc, bg=tint) | rev)
            else:                                    # no room for a method column: just the name
                _put(stdscr, y, cx, _fit(nm_txt, cell), pal.style(elem, y, cx, h, w, selected=foc, bg=tint) | rev)
    # the catalog scrolls horizontally by column; show which columns are in view on the bottom border
    _scrollbar_h(stdscr, pal, ctop + cath - 1, ril, riw, ps.rcol_left, ncols, total_cols, h, w)

    from .. import actions
    status = f' profile: {prof or "—"}    edits → {actions.edit_target(ctx)[1]}'
    if note:
        status += f'    {note}'
    # marker legend for the profiles pane — right-aligned on the status bar so the keys get two
    # full rows below. ● directly active (in configs:), ◐ active only via a +include, ○ inactive,
    # ▸ star-filtered.
    legend = '● active  ◐ inherited  ○ inactive  ▸ starred '
    lg_x = max(0, w - len(legend))
    _put(stdscr, h - 3, 0, _fit(status, max(1, lg_x - 1)), pal.style('status_line', h - 3, 0, h, w))
    _put(stdscr, h - 3, lg_x, _fit(legend, w - lg_x), pal.style('status_line', h - 3, lg_x, h, w))
    nav1 = (' j/k move · g/G top/bottom · h/l expand · tab/⏎ components · / find · F filter · A attrs ')
    nav2 = (' space member · m method · a active · * star · ~ removed · + include · n/d new/del · q quit ')
    _put(stdscr, h - 2, 0, _fit(nav1.ljust(w), w), pal.style('footer', h - 2, 0, h, w))
    _put(stdscr, h - 1, 0, _fit(nav2.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
    stdscr.refresh()


# -- F2 primitive: a single-line text-input modal -------------------------
def _input_box(stdscr, pal, title, initial='', complete=None, toggle=None):
    '''Modal single-line text entry over the current screen. Returns the string on Enter, or None
    on Esc. Handles printable ASCII + backspace. `complete` is an optional list of candidate strings:
    the first that extends the current text shows as a dim ghost, and Tab accepts it. `toggle` is an
    optional (label, initial_bool): it adds a checkbox line that Tab flips (when there's no
    completion to accept), and the box then returns (text, checked) — (None, checked) on Esc.'''
    h, w = stdscr.getmaxyx()
    box_w = min(max(len(title) + 4, 60), max(24, w - 2))
    box_h = 5 + (1 if toggle else 0)
    y0, x0 = max(0, (h - box_h) // 2), max(0, (w - box_w) // 2)
    border = pal.get('accent') | curses.A_BOLD
    ghost_attr = pal.get('dim')
    buf = list(initial)
    checked = bool(toggle[1]) if toggle else False

    def _match(s):
        return next((c for c in (complete or []) if c.startswith(s) and c != s), None) if s else None

    def _ret(text):
        return (text, checked) if toggle else text

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
            _put(stdscr, y0 + box_h - 1, x0 + 2,
                 ' enter · esc' + (' · tab' if (complete or toggle) else '') + ' ', border)
            s = ''.join(buf)
            _put(stdscr, y0 + 2, x0 + 2, _fit(s, box_w - 4).ljust(box_w - 4), curses.A_UNDERLINE)
            m = _match(s)
            if m and len(s) < box_w - 4:                 # dim autocomplete ghost after the text
                _put(stdscr, y0 + 2, x0 + 2 + len(s), _fit(m[len(s):], box_w - 4 - len(s)), ghost_attr)
            if toggle:                                   # a checkbox line (tab toggles it)
                mark = '☑' if checked else '☐'
                _put(stdscr, y0 + 3, x0 + 2, _fit(f'{mark} {toggle[0]}', box_w - 4),
                     border if checked else ghost_attr)
            try:
                stdscr.move(y0 + 2, x0 + 2 + min(len(s), box_w - 5))
            except curses.error:
                pass
            stdscr.refresh()
            ch = stdscr.getch()
            if ch == 27:
                return _ret(None)
            if ch in (ord('\n'), curses.KEY_ENTER):
                return _ret(''.join(buf))
            if ch == ord('\t'):
                if m:
                    buf = list(m)
                elif toggle:
                    checked = not checked
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                if buf:
                    buf.pop()
            elif ch == 21:                       # Ctrl-U: clear the line (replace a prefilled value)
                buf = []
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
    pal.use_page(screen)
    if pal.gradient:
        _fill_bg(stdscr, pal, h, w)
    _draw_nav(stdscr, pal, screen, h, w)
    it, il, ih, iw = _panel(stdscr, pal, 1, 0, h - 3, w,
                            'machine settings  ·  your values here override the built-in defaults',
                            True, h, w)
    y = it
    for i, key in enumerate(cs.keys):
        if y + 1 >= it + ih:
            break
        info = cs.settings[key]
        sel = i == cs.cur
        if sel:
            _put(stdscr, y, il, ' ' * iw, pal.fill(y, il, h, w, selected=True))
        # where does this setting live now, and (when unset) where would a fresh edit land?
        src = info.get('source')
        tgt = info.get('target')                          # named target: 'top config' | primary name
        if isinstance(src, str) and src.startswith('env '):
            loc, set_, tail = src + ' overrides config', True, ''
        elif info.get('home') == 'local':
            loc, set_, tail = 'local (top config)', True, ''
        elif info.get('home') == 'primary':
            loc, set_, tail = f'primary: {info.get("home_label")}', True, ''
        else:                                             # at default -> show the edit destination by name
            loc, set_, tail = 'built-in default', False, (f'  → edits: {tgt}' if tgt else '')
        tag = f'   · {loc}{tail}'
        _put(stdscr, y, il, _fit(f'{key:18} {_setting_str(info["kind"], info["value"], key)}', iw),
             pal.style('label' if sel else 'component', y, il, h, w, selected=sel))
        _put(stdscr, y, il + max(0, iw - len(tag) - 1), _fit(tag, len(tag)),
             pal.style('scope_choice' if set_ else 'info_dim', y, il, h, w, selected=sel))
        _put(stdscr, y + 1, il, _fit(f'   {info["desc"]}  (man: {info["man"]})', iw),
             pal.style('info_dim', y + 1, il, h, w))
        y += 3
    from .. import actions
    cur_key = cs.keys[cs.cur] if cs.keys else None
    tgt = cs.settings.get(cur_key, {}).get('target') if cur_key else None
    status = f' {cur_key}: edits → {tgt}' if tgt else f' edits → {actions.edit_target(ctx)[1]}'
    if note:
        status += f'    {note}'
    navf = ' j/k move · enter/space edit · m local↔primary · t theme · 1-6 screens · q quit '
    _put(stdscr, h - 2, 0, _fit(status, w), pal.style('status_line', h - 2, 0, h, w))
    _put(stdscr, h - 1, 0, _fit(navf.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
    stdscr.refresh()


# -- Theme editor (its own screen, key 6) ---------------------------------
class ThemeScreen:
    '''Two lists over one sample page: the shared color MAP (name -> #rrggbb) and the focused page's
    ROLE styles (fg/bg/effects, fg/bg referencing a map name or a literal). Tab toggles focus; a-e
    cycles the page. Edits write via actions.set_theme_value; the caller re-instantiates the Palette
    so the sample repaints instantly.'''
    def __init__(self, ctx):
        self.ctx = ctx
        self.page = 0                              # focused page (index into ALL_PAGES, incl. 'theme')
        self.focus = 'map'                         # 'map' | 'roles'
        self.map_cur = self.map_top = 0
        self.role_cur = self.role_top = 0
        self.map_ncols = 1                         # set during draw; the h/l column stride
        self.map_rows_per_col = 10 ** 6
        self.reload()

    def reload(self):
        from .theme import COLOR_MAP, resolve_theme
        self.theme = self.ctx.config.theme()
        names = list(COLOR_MAP)
        for n in (self.theme.get('colors') or {}):
            if n not in names:
                names.append(n)                     # user-added map colors after the built-ins
        self.map_names = names
        self.colors, self.pages = resolve_theme(self.theme)      # resolved rgb
        self.map_cur = min(self.map_cur, max(0, len(names) - 1))
        self.role_cur = min(self.role_cur, max(0, len(self.role_list()) - 1))

    def page_name(self):
        from .theme import ALL_PAGES                    # DEMO_PAGES + 'theme' (the editor's own page)
        return ALL_PAGES[self.page]

    def role_list(self):
        from .theme import PAGE_ROLES
        # the roles THIS page uses, plus the two gradient endpoints as single-color pseudo-roles
        return PAGE_ROLES.get(self.page_name(), []) + ['@grad_from', '@grad_to']

    def grad_override(self, which):
        g = ((self.theme.get('pages') or {}).get(self.page_name()) or {}).get('gradient')
        return g.get(which) if isinstance(g, dict) else None

    def grad_ref(self, which):
        '''The authored ref (map name or literal) for a gradient endpoint, else the built-in
        default as a hex — what the user edits.'''
        from .theme import BUILTIN_GRADIENTS
        ov = self.grad_override(which)
        if ov not in (None, ''):
            return ov
        page = self.page_name()
        dflt = BUILTIN_GRADIENTS.get(page, BUILTIN_GRADIENTS['components'])
        return _hex(dflt[0 if which == 'from' else 1])

    def grad_rgb(self, which):
        '''The resolved rgb of a gradient endpoint on the focused page (for the swatch).'''
        return self.pages[self.page_name()]['grad'][0 if which == 'from' else 1]

    def cur_color(self):
        return self.map_names[self.map_cur] if self.map_names else None

    def cur_role(self):
        rl = self.role_list()
        return rl[self.role_cur] if rl else None

    def color_override(self, name):
        return (self.theme.get('colors') or {}).get(name)

    def role_override(self, role):
        return ((self.theme.get('pages') or {}).get(self.page_name()) or {}).get(role)

    def role_ref(self, role):
        '''Effective fg/bg refs (map name or literal) for a role = built-in default overlaid by the
        page's override — what the user is editing (before resolution to rgb).'''
        from .theme import ROLE_DEFAULTS
        st = dict(ROLE_DEFAULTS.get(role, {}))
        ov = self.role_override(role)
        if isinstance(ov, dict):
            st.update(ov)
        return st

    def role_style(self, role):
        '''Resolved rgb style {fg, bg, bold, ...} for a role on the focused page (for the swatch).'''
        return self.pages[self.page_name()]['roles'].get(role, {'fg': (235, 235, 235), 'bg': None})

    def page_gradient_enabled(self, page):
        g = (((self.theme.get('pages') or {}).get(page) or {}).get('gradient') or {})
        return g.get('enabled') not in (False, 'false', 'no', 'off')


def _hex(rgb):
    return '#%02x%02x%02x' % (rgb[0], rgb[1], rgb[2])


def _eff_flags(st):
    return ((curses.A_BOLD if st.get('bold') else 0)
            | (curses.A_UNDERLINE if st.get('underline') else 0)
            | (curses.A_REVERSE if st.get('reverse') else 0))


# A faithful mock of each real screen — a header line, rows (first selected), and footer lines —
# so the sample REPRESENTS that page and uses that page's own roles. A row is a list of
# (text, width, role) segments; width 0 = run to the panel edge. `badge` is an optional top-right
# chrome chip (text, role).
_SAMPLES = {
    'components': {
        'badge': (' ⚠ 2 ', 'issue_warning'),
        'header': f'{"COMPONENT":15}{"DRIVER":9}{"VER":7}STATUS',
        'rows': [
            [('ripgrep', 15, 'component'), ('apt', 9, 'driver'), ('14.1', 7, 'version'),
             ('installed', 10, 'installed'), ('[i]', 0, 'op_install')],
            [('neovim', 15, 'unit'), ('tarball', 9, 'driver'), ('0.9', 7, 'version'),
             ('outdated', 10, 'outdated'), ('[u]', 0, 'op_upgrade')],
            [('btop', 15, 'component'), ('native', 9, 'driver'), ('—', 7, 'version'),
             ('missing', 10, 'missing')],
            [('steam', 15, 'unit'), ('flatpak', 9, 'driver'), ('1.0', 7, 'version'),
             ('locked', 10, 'locked'), ('[L]', 0, 'op_lock')],
        ],
        'foot': [('ripgrep — fast recursive search', 'info'),
                 ('methods: apt · tarball · cargo', 'methods'),
                 (' selected: ripgrep    staged: 2 ', 'status_line')],
    },
    'profiles': {
        'header': f'{"PROFILES":22}COMPONENTS IN dev',
        'rows': [
            [('dev', 22, 'profile'), ('btop', 0, 'component')],
            [('+base', 22, 'link'), ('ripgrep', 0, 'component')],
            [('web', 22, 'profile'), ('neovim', 0, 'component')],
        ],
        'foot': [('dev = base + your tools', 'info'), ('3 profiles active', 'info_dim'),
                 (' selected: dev ', 'status_line')],
    },
    'plugins': {
        'header': f'{"PLUGIN":22}STATUS',
        'rows': [
            [('configsys-user', 22, 'component'), ('★ primary', 0, 'info')],
            [('void-linux', 22, 'unit'), ('code', 0, 'installed')],
            [('theme-rose', 22, 'unit'), ('unsynced', 0, 'missing')],
            [('acme-corp', 22, 'unit'), ('quarantined', 0, 'untrusted')],
        ],
        'foot': [('configsys-user — dotfiles + settings', 'info'),
                 ('4 declared · 1 primary', 'info_dim'), (' selected: configsys-user ', 'status_line')],
    },
    'dotfiles': {
        'header': f'{"COMPONENT":14}{"STATE":13}{"LINK":22}SOURCE',
        'rows': [
            [('neovim', 14, 'component'), ('linked', 13, 'installed'),
             ('~/.config/nvim', 22, 'unit'), ('<plugin>/neovim.cfs', 0, 'installed')],
            [('git', 14, 'component'), ('+ managed', 13, 'outdated'),
             ('~/.gitconfig', 22, 'unit'), ('<plugin>/git-dotfiles.cfs', 0, 'outdated')],
            [('zsh-glue', 14, 'component'), ('loader-on', 13, 'installed'),
             ('~/.config/zsh/conf.d', 22, 'unit'), ('rc hookup', 0, 'installed')],
            [('htop', 14, 'component'), ('! unmanaged', 13, 'missing'),
             ('~/.config/htop', 22, 'unit'), ('(none)', 0, 'missing')],
        ],
        'foot': [('git — capture to link ~/.gitconfig', 'info_dim'),
                 ('4 targets · 1 to capture', 'info_dim'),
                 (' ↵ link · c capture · m migrate · C/L/M = all ', 'status_line')],
    },
    'config': {
        'header': f'{"SETTING":20}VALUE',
        'rows': [
            [('scope', 20, 'component'), ('system', 12, 'scope_choice'), ('· override', 0, 'info_dim')],
            [('driver-preference', 20, 'component'), ('native…', 12, 'scope'), ('· default', 0, 'info_dim')],
            [('auto-tighten', 20, 'component'), ('false', 12, 'scope'), ('· default', 0, 'info_dim')],
        ],
        'foot': [('scope — default install location', 'info_dim'), ('4 settings', 'info_dim'),
                 (' ↵ edit ', 'status_line')],
    },
}


def _sample_theme_page(stdscr, pal, y0, x0, hh, ww):
    '''Mock of the Theme editor's OWN page (`f`): its two STACKED left panels — color map above page
    roles — plus a status + footer line, and no configsys/OS chrome. So previewing 'theme' looks like
    the real Theme page, not the generic single-panel content screens.'''
    pal.use_page('theme')

    def putl(ry, rx, text, role, *, sel=False):
        if 0 <= ry < hh and 0 <= rx < ww - 1:
            _put(stdscr, y0 + ry, x0 + rx, _fit(text, ww - 1 - rx),
                 pal.style(role, ry, rx, hh, ww, selected=sel))

    for yy in range(hh):                               # page background (gradient or flat)
        bg = pal.fill(yy, 0, hh, ww) if pal.gradient else pal.style('unit', yy, 0, hh, ww)
        _put(stdscr, y0 + yy, x0, ' ' * ww, bg)
    if hh < 9 or ww < 26:
        pal.use_page('theme')
        return

    avail = hh - 2                                     # reserve the status + footer rows
    top_h = max(4, avail * 2 // 5)

    def box(ry, bh, title):                            # a mini bordered panel (info_dim border)
        putl(ry, 0, '┌' + '─' * (ww - 2) + '┐', 'info_dim')
        for r in range(1, bh - 1):
            putl(ry + r, 0, '│', 'info_dim')
            putl(ry + r, ww - 1, '│', 'info_dim')
        putl(ry + bh - 1, 0, '└' + '─' * (ww - 2) + '┘', 'info_dim')
        putl(ry, 2, f' {title} ', 'menu_header')

    def selbar(ry):
        _put(stdscr, y0 + ry, x0 + 1, ' ' * (ww - 2), pal.fill(ry, 1, hh, ww, selected=True))

    box(0, top_h, 'color map (shared)')                # TOP panel: the shared colours
    for i, (name, swrole) in enumerate([('accent', 'accent'), ('fg_main', 'label'),
                                        ('bg_dim', 'info_dim'), ('sel_bg', 'component')]):
        yy = 1 + i
        if yy >= top_h - 1:
            break
        sel = i == 0
        if sel:
            selbar(yy)
        putl(yy, 2, '██', swrole)                      # a swatch, in a representative theme colour
        putl(yy, 5, name, 'label' if sel else 'component', sel=sel)

    box(top_h, avail - top_h, 'page roles — theme')    # BOTTOM panel: this page's role styles
    for i, role in enumerate(['label', 'component', 'footer', 'status_line', 'menu_header']):
        yy = top_h + 1 + i
        if yy >= avail - 1:
            break
        sel = i == 0
        if sel:
            selbar(yy)
        putl(yy, 2, 'Aa', role)                        # preview each role in its OWN style
        putl(yy, 5, role, 'label' if sel else 'component', sel=sel)

    putl(hh - 2, 0, _fit(' terminal color: 24-bit   ·   edits → your config ', ww).ljust(ww), 'status_line')
    putl(hh - 1, 0, _fit(' tab · j/k · a-f page · ↵ set colour · s save · q ', ww).ljust(ww), 'footer')
    pal.use_page('theme')


def _sample_page(stdscr, pal, page, y0, x0, hh, ww):
    '''Render a mock of the REAL `page` (its layout + its own roles) in that page's colors + gradient,
    so cycling pages shows a faithful, distinct preview. Switches the palette's active page; the
    caller restores.'''
    if hh < 6 or ww < 24:
        return
    if page == 'theme':                                # the editor's own page has a distinct layout
        _sample_theme_page(stdscr, pal, y0, x0, hh, ww)
        return
    pal.use_page(page)
    for yy in range(hh):
        bg = pal.fill(yy, 0, hh, ww) if pal.gradient else pal.style('unit', yy, 0, hh, ww)
        _put(stdscr, y0 + yy, x0, ' ' * ww, bg)
    spec = _SAMPLES.get(page, _SAMPLES['components'])

    def put(yy, x, text, role, *, sel=False):
        if 0 <= yy < hh and 0 <= x < ww - 1:
            _put(stdscr, y0 + yy, x0 + x, _fit(text, ww - 1 - x),
                 pal.style(role, yy, x, hh, ww, selected=sel))

    put(0, 1, ' configsys ', 'label')                              # shared chrome
    put(0, 13, 'Pop!_OS 22.04', 'os')
    if spec.get('badge') and ww > 24:
        put(0, ww - len(spec['badge'][0]) - 1, spec['badge'][0], spec['badge'][1])
    put(1, 1, spec['header'], 'menu_header')

    foot = spec['foot']
    maxrows = hh - 2 - len(foot) - 1
    for ri, row in enumerate(spec['rows'][:max(0, maxrows)]):
        yy, sel = 2 + ri, ri == 0                                  # first row selected -> cursor bar
        if sel and pal.gradient:
            _put(stdscr, y0 + yy, x0, ' ' * ww, pal.fill(yy, 0, hh, ww, selected=True))
        x = 1
        for si, (text, wd, role) in enumerate(row):
            disp = ('» ' + text) if (sel and si == 0) else (('  ' + text) if si == 0 else text)
            width = wd or (ww - x)
            put(yy, x, _fit(disp, width), role, sel=sel)
            x += wd if wd else (len(disp) + 1)
    fy = hh - len(foot) - 1
    for i, (text, role) in enumerate(foot):
        put(fy + i, 1, text, role)
    put(hh - 1, 1, _fit(' j/k move · space · q ', ww - 2).ljust(ww - 2), 'footer')
    pal.use_page('theme')


def _ref_str(ref):
    '''Show a role's fg/bg reference as-authored: a map name, a literal, or — for the gradient.'''
    if ref in (None, '', 'none', 'false', False):
        return '—'
    return str(ref)


def _valid_ref(val, map_names):
    '''A role fg/bg / gradient endpoint is valid if it names a map color or parses as a literal.'''
    from .theme import parse_color
    v = (val or '').strip()
    return v in map_names or parse_color(v) is not None


def _draw_theme(stdscr, pal, ts, ctx, note, screen):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    pal.use_page('theme')
    if pal.gradient:
        _fill_bg(stdscr, pal, h, w)
    _draw_nav(stdscr, pal, 'theme', h, w)
    ts.reload()
    from .theme import ALL_PAGES
    page = ALL_PAGES[ts.page]
    body_h, lw = h - 3, max(42, 5 * w // 11)
    map_h = max(6, body_h * 2 // 5)

    # -- List 1: the shared color map (name -> #rrggbb), two columns when the panel is wide enough --
    m_it, m_il, m_ih, m_iw = _panel(stdscr, pal, 1, 0, map_h, lw, 'color map (shared)',
                                    ts.focus == 'map', h, w)
    ncols = 2 if m_iw >= 60 else 1
    rows_per_col = max(1, -(-len(ts.map_names) // ncols))      # ceil
    ts.map_ncols, ts.map_rows_per_col = ncols, rows_per_col
    col_w = m_iw // ncols
    nw = 12 if ncols == 2 else 14
    ts.map_top = _scroll_top(ts.map_cur % rows_per_col, ts.map_top, m_ih, rows_per_col)
    for i, name in enumerate(ts.map_names):
        col, row = divmod(i, rows_per_col)
        if not (ts.map_top <= row < ts.map_top + m_ih):
            continue
        y, x = m_it + (row - ts.map_top), m_il + col * col_w
        sel = i == ts.map_cur and ts.focus == 'map'
        rgb = ts.colors.get(name, (235, 235, 235))
        if sel:
            _put(stdscr, y, x, ' ' * col_w, pal.fill(y, x, h, w, selected=True))
        _put(stdscr, y, x + 1, ' ██ ', pal.rgb_attr(rgb))
        mark = '*' if ts.color_override(name) is not None else ' '
        _put(stdscr, y, x + 6, _fit(f'{mark}{name:{nw}} {_hex(rgb)}', col_w - 6),
             pal.style('label' if sel else 'component', y, x + 6, h, w, selected=sel))
    _scrollbar_v(stdscr, pal, m_it, m_il + m_iw, m_ih, ts.map_top, m_ih, rows_per_col, h, w)

    # -- List 2: the focused page's role styles, plus the gradient endpoints as single-color rows --
    roles = ts.role_list()
    ts.role_cur = min(ts.role_cur, max(0, len(roles) - 1))
    r_it, r_il, r_ih, r_iw = _panel(stdscr, pal, 1 + map_h, 0, body_h - map_h, lw,
                                    _fit(f'page roles — {page}  (a-f)', lw - 4), ts.focus == 'roles',
                                    h, w)
    ts.role_top = _scroll_top(ts.role_cur, ts.role_top, r_ih, len(roles))
    for vis, i in enumerate(range(ts.role_top, min(len(roles), ts.role_top + r_ih))):
        role, y = roles[i], r_it + vis
        sel = i == ts.role_cur and ts.focus == 'roles'
        if sel:
            _put(stdscr, y, r_il, ' ' * r_iw, pal.fill(y, r_il, h, w, selected=True))
        if role.startswith('@grad'):                          # a gradient endpoint: one color, no fx
            which = 'from' if role == '@grad_from' else 'to'
            _put(stdscr, y, r_il + 1, ' ██ ', pal.rgb_attr(ts.grad_rgb(which)))
            mark = '*' if ts.grad_override(which) is not None else ' '
            _put(stdscr, y, r_il + 6, _fit(f'{mark}gradient {which:5} {_ref_str(ts.grad_ref(which))}',
                 r_iw - 6), pal.style('label' if sel else 'component', y, r_il + 6, h, w, selected=sel))
            continue
        ref, rst = ts.role_ref(role), ts.role_style(role)
        sw = pal.rgb_pair(rst['fg'], rst['bg']) if rst.get('bg') else pal.rgb_attr(rst['fg'])
        _put(stdscr, y, r_il + 1, ' Aa ', sw | _eff_flags(rst))
        eff = ''.join(c for c, f in (('b', 'bold'), ('u', 'underline'), ('r', 'reverse')) if rst.get(f))
        mark = '*' if ts.role_override(role) is not None else ' '
        txt = f'{mark}{role:14.14} {_ref_str(ref.get("fg")):>8.8}/{_ref_str(ref.get("bg")):<8.8} {eff}'
        _put(stdscr, y, r_il + 6, _fit(txt, r_iw - 6),
             pal.style('label' if sel else 'component', y, r_il + 6, h, w, selected=sel))
    _scrollbar_v(stdscr, pal, r_it, r_il + r_iw, r_ih, ts.role_top, r_ih, len(roles), h, w)

    # -- the sample page (right) --
    rx, rw = lw + 1, w - lw - 1
    st_it, st_il, st_ih, st_iw = _panel(stdscr, pal, 1, rx, body_h, rw,
                                        _fit(f'sample page — {page}', rw - 4), False, h, w)
    _sample_page(stdscr, pal, page, st_it, st_il, st_ih, st_iw)
    pal.use_page('theme')

    from .. import actions
    status = f' terminal color: {pal.color_mode}   ·   edits → {actions.edit_target(ctx)[1]}'
    if note:
        status += f'    {note}'
    if ts.focus == 'map':
        navf = (' tab→roles · h/l/j/k · a-f page · ↵ set #rrggbb · n new · x/r remove · '
                's save · L load · q ')
    else:
        navf = (' tab→map · j/k · a-f page · ↵ fg · B bg · o/u/v fx · r reset · p grad on/off · '
                'D copy-page · s save · L load · q ')
    _put(stdscr, h - 2, 0, _fit(status, w), pal.style('status_line', h - 2, 0, h, w))
    _put(stdscr, h - 1, 0, _fit(navf.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
    stdscr.refresh()


# -- Plugins screen -------------------------------------------------------
# Column headers; widths are computed per-draw to fit content (name/source show full length).
_PLUGIN_HEADERS = ['name', 'source', 'ref', 'remote-ref', 'abi', 'code', 'provides']
_DIFF_ELEM = {'add': 'diff_add', 'del': 'diff_del', 'hunk': 'diff_hunk',
              'meta': 'diff_meta', 'ctx': 'info_dim'}


class PluginScreen:
    '''Two-pane Plugins screen. TOP: a `tree`-style table of declared plugins (incl. transitive)
    with name│source│ref│remote-ref│abi│code│provides columns — j/k select, h/l scroll columns.
    BOTTOM: a diff of what updating the selected plugin to its remote-ref would change (fetched on
    demand; files as headers; hjkl scroll). Tab cycles focus table→diff→next file→table; Shift-Tab
    reverses. A skin over configsys.actions.plugin_* — add/remove/sync/bless/update/trust.'''

    def __init__(self, ctx):
        self.ctx = ctx
        self.cur = 0
        self.top = 0
        self.hscroll = 0                 # horizontal scroll across the columns
        self.focus = 'table'             # 'table' | 'diff'
        self.remote = {}                 # dir_name -> ref(str) | 'pending' | None(unreachable/none)
        self._remote_gen = 0
        self.dfile = 0                   # selected file within the loaded diff
        self.dtop = 0                    # vertical scroll within the diff file
        self.dhscroll = 0                # horizontal scroll within the diff
        self.diff_key = None             # (name, from_ref, to_ref) the loaded diff belongs to
        self.diff_files = []
        self.diff_note = ''
        self.reload()

    def reload(self):
        from .. import plugins
        self.tree = plugins.declared_tree(self.ctx.paths.user_config_file, self.ctx.paths.plugins_dir)
        self.rows = plugins.status(self.ctx.paths.plugins_dir, [t['decl'] for t in self.tree],
                                   trust_file=self.ctx.paths.plugin_trust_file)
        self.cur = min(self.cur, max(0, len(self.rows) - 1))
        self._invalidate_diff()
        self._start_remote()

    def cur_row(self):
        return self.rows[self.cur] if 0 <= self.cur < len(self.rows) else None

    def cur_tree(self):
        return self.tree[self.cur] if 0 <= self.cur < len(self.tree) else None

    def _start_remote(self):
        '''Resolve each plugin's remote-ref on a daemon thread (read-only `git ls-remote`); the
        table shows '…' until each lands. Like ProfileScreen._warm_cache: the menu loop blocks in
        getch() while idle, so cells fill without stalling screen entry on the network.'''
        from .. import plugins
        self._remote_gen += 1
        gen, rows = self._remote_gen, list(self.rows)
        for r in rows:
            self.remote.setdefault(plugins.dir_name(r['source']), 'pending')

        def run():
            for r in rows:
                if self._remote_gen != gen:              # a reload superseded us
                    return
                key = plugins.dir_name(r['source'])
                try:
                    ref, _kind = plugins.latest_ref(self.ctx.runner, r['source'])
                    self.remote[key] = ref               # str, or None if unreachable / no ref
                except Exception:                        # noqa: BLE001 — never let it crash
                    self.remote[key] = None
        threading.Thread(target=run, daemon=True).start()

    def _invalidate_diff(self):
        self.diff_key, self.diff_files, self.diff_note = None, [], ''
        self.dfile = self.dtop = self.dhscroll = 0

    def load_diff(self):
        '''Fetch + parse the selected plugin's diff against its remote-ref (what updating pulls in),
        cached by (name, ref, remote). No-op if already loaded; retries while the remote is pending.'''
        from .. import plugins
        row, node = self.cur_row(), self.cur_tree()
        if row is None or node is None:
            self.diff_key, self.diff_files, self.diff_note = None, [], 'no plugin selected'
            return
        key = plugins.dir_name(row['source'])
        remote = self.remote.get(key)
        target = remote if isinstance(remote, str) else None
        ident = (key, row['ref'], target)
        if ident == self.diff_key:
            return                                       # already loaded this exact diff
        if remote == 'pending':
            self.diff_files, self.diff_note = [], 'resolving remote-ref…'
            return                                       # not cached — retry once it lands
        self.dfile = self.dtop = self.dhscroll = 0
        if not target:
            self.diff_key, self.diff_files = ident, []
            self.diff_note = 'no upstream ref to compare against'
            return
        files, err = plugins.diff_against_ref(self.ctx.runner, self.ctx.paths.plugins_dir,
                                              node['decl'], target)
        self.diff_key, self.diff_files = ident, files
        self.diff_note = err or ('' if files else 'up to date — nothing to pull in')
        self.dfile = min(self.dfile, max(0, len(files) - 1))


def _plugin_tree_prefix(node):
    '''The ├─ │ └─ prefix for a tree row from its ancestry is-last flags. Roots sit flush-left, and
    a depth-1 child's connector starts at column 0 (under the root name's first letter) — the root
    level contributes no indent (flags[1:-1]), so the tree stays tight against the name column.'''
    flags = node['last']
    if node['depth'] == 0:
        return ''
    return ''.join('   ' if f else '│  ' for f in flags[1:-1]) + ('└─ ' if flags[-1] else '├─ ')


def _plugin_cells(row, node, remote):
    '''The seven column strings for a plugin row (name carries the tree prefix + ★).'''
    rref = '…' if remote == 'pending' else (remote if isinstance(remote, str) else '—')
    return [f'{_plugin_tree_prefix(node)}{"★" if row["primary"] else ""}{row["name"]}',
            row['source'], row['ref'] or '—', rref,
            'ok' if row['abi_ok'] else f'≠{row["requires_abi"]}',
            row['code_state'] if row['has_code'] else '—',
            ','.join(row['provides']) if isinstance(row['provides'], dict) and row['provides'] else '—']


def _put_hscroll(stdscr, y, left, win_w, vx, hscroll, text, attr):
    '''Draw `text` starting at virtual column `vx`, clipped to a window `win_w` wide scrolled by
    `hscroll` — the primitive behind the plugins table's horizontal (h/l) scroll.'''
    start = vx - hscroll
    if start >= win_w or start + len(text) <= 0:
        return
    if start < 0:
        text, start = text[-start:], 0
    _put(stdscr, y, left + start, text[:win_w - start], attr)


def _plugin_remote_elem(row, remote):
    if remote == 'pending' or not isinstance(remote, str):
        return 'info_dim'
    return 'installed' if remote == (row['ref'] or None) else 'outdated'   # green=up-to-date, amber=update


def _plugin_code_elem(row):
    return {'trusted': 'installed', 'untrusted': 'untrusted', 'changed': 'untrusted',
            'none': 'info_dim', 'unsynced': 'info_dim'}.get(row['code_state'], 'info_dim')


def _draw_plugins_table(stdscr, pal, pl, h, w, top, table_h):
    from .. import plugins
    tit, til, tih, tiw = _panel(stdscr, pal, top, 0, table_h, w, 'plugins (tree)',
                                pl.focus == 'table', h, w)
    if not pl.rows:
        _put(stdscr, tit, til, _fit('(no plugins declared — a to add)', tiw),
             pal.style('info_dim', tit, til, h, w))
        return
    # one cell-set per row; columns are sized to their longest cell so name/source show in full
    remotes = [pl.remote.get(plugins.dir_name(r['source'])) for r in pl.rows]
    cells_by_row = [_plugin_cells(r, pl.tree[i], remotes[i]) for i, r in enumerate(pl.rows)]
    widths = [max(len(_PLUGIN_HEADERS[c]), max((len(cs[c]) for cs in cells_by_row), default=0))
              for c in range(len(_PLUGIN_HEADERS))]
    xs, vx = [], 0
    for wd in widths:
        xs.append(vx)
        vx += wd + 1                                     # one space between columns
    virt_w = vx - 1
    pl.hscroll = max(0, min(pl.hscroll, max(0, virt_w - tiw)))   # clamp: no scrolling past the end
    # sticky column header on the first inner row, then rows scroll below it
    for hdr, vx0 in zip(_PLUGIN_HEADERS, xs):
        _put_hscroll(stdscr, tit, til, tiw, vx0, pl.hscroll, hdr, pal.style('menu_header', tit, til, h, w))
    rows_h = tih - 1
    pl.top = _scroll_top(pl.cur, pl.top, rows_h, len(pl.rows))
    for vis, i in enumerate(range(pl.top, min(len(pl.rows), pl.top + rows_h))):
        row, y, sel = pl.rows[i], tit + 1 + vis, i == pl.cur
        if sel:
            _put(stdscr, y, til, ' ' * tiw, pal.fill(y, til, h, w, selected=True))
        healthy = row['synced'] and row['abi_ok'] and row['checksum'] != 'mismatch'
        base = 'component' if healthy else 'info_dim'
        elems = [base, 'info_dim', 'info', _plugin_remote_elem(row, remotes[i]),
                 'installed' if row['abi_ok'] else 'error', _plugin_code_elem(row), 'info_dim']
        for cell, wd, vx0, el in zip(cells_by_row[i], widths, xs, elems):
            style = pal.style('label' if sel else el, y, til, h, w, selected=sel)
            _put_hscroll(stdscr, y, til, tiw, vx0, pl.hscroll, cell.ljust(wd), style)
    _scrollbar_v(stdscr, pal, tit + 1, til + tiw, rows_h, pl.top, rows_h, len(pl.rows), h, w)
    _scrollbar_h(stdscr, pal, tit + table_h - 1, til, tiw, pl.hscroll, tiw, virt_w, h, w)


def _draw_plugins_diff(stdscr, pal, pl, h, w, top, diff_h):
    from .. import plugins
    row = pl.cur_row()
    title = 'diff'
    if row is not None:
        remote = pl.remote.get(plugins.dir_name(row['source']))
        to = remote if isinstance(remote, str) else '—'
        title = f'diff · {row["name"]} · {row["ref"] or "HEAD"} → {to}'
    dit, dil, dih, diw = _panel(stdscr, pal, top, 0, diff_h, w, title, pl.focus == 'diff', h, w)
    files = pl.diff_files
    if not files:
        msg = pl.diff_note or 'Tab here to review what an update would change'
        _put(stdscr, dit, dil, _fit(msg, diw), pal.style('info_dim', dit, dil, h, w))
        return
    pl.dfile = max(0, min(pl.dfile, len(files) - 1))
    f = files[pl.dfile]
    added = sum(1 for k, _t in f['lines'] if k == 'add')
    removed = sum(1 for k, _t in f['lines'] if k == 'del')
    header = f'[{pl.dfile + 1}/{len(files)}] {f["path"]}   +{added} -{removed}   (Tab: next file)'
    _put(stdscr, dit, dil, _fit(header, diw), pal.style('accent', dit, dil, h, w))
    body_h = dih - 1
    lines = f['lines']
    pl.dtop = max(0, min(pl.dtop, max(0, len(lines) - body_h)))
    maxlen = max((len(t) for _k, t in lines), default=0)
    pl.dhscroll = max(0, min(pl.dhscroll, max(0, maxlen - diw)))
    for vis, i in enumerate(range(pl.dtop, min(len(lines), pl.dtop + body_h))):
        kind, txt = lines[i]
        y = dit + 1 + vis
        _put(stdscr, y, dil, _fit(txt[pl.dhscroll:], diw),
             pal.style(_DIFF_ELEM.get(kind, 'info_dim'), y, dil, h, w))
    _scrollbar_v(stdscr, pal, dit + 1, dil + diw, body_h, pl.dtop, body_h, len(lines), h, w)
    _scrollbar_h(stdscr, pal, dit + diff_h - 1, dil, diw, pl.dhscroll, diw, maxlen, h, w)


def _draw_plugins(stdscr, pal, pl, ctx, note, screen):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    pal.use_page(screen)
    if pal.gradient:
        _fill_bg(stdscr, pal, h, w)
    _draw_nav(stdscr, pal, screen, h, w)
    top, body_h = 1, h - 3
    table_h = max(6, body_h * 2 // 5)                    # diff gets the larger share (~3/5); table the rest
    diff_h = body_h - table_h
    _draw_plugins_table(stdscr, pal, pl, h, w, top, table_h)
    _draw_plugins_diff(stdscr, pal, pl, h, w, top + table_h, diff_h)

    status = f' {len(pl.rows)} plugin(s) · focus: {pl.focus}'
    if note:
        status += f'    {note}'
    navf = (' tab focus · j/k · h/l scroll · a add · x rm · s/S sync · b/B bless · u/U update · '
            'v ref · t trust · T trust-all · 1-6 · q ')
    _put(stdscr, h - 2, 0, _fit(status, w), pal.style('status_line', h - 2, 0, h, w))
    _put(stdscr, h - 1, 0, _fit(navf.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
    stdscr.refresh()


# -- Dotfiles screen ------------------------------------------------------
# state -> theme element. `managed` (a .cfs marker exists but nothing is captured yet — capture to
# link) and `unmanaged` (a real file we don't manage — at risk) both want attention; `loader-on/off`
# are the per-shell glue loaders (zsh-glue/fish-glue).
_DF_STATE_ELEM = {'linked': 'installed', 'adopted': 'unit', 'managed': 'outdated',
                  'unmanaged': 'missing', 'template': 'info_dim', 'empty': 'info_dim',
                  'loader-on': 'installed', 'loader-off': 'info_dim'}
_DF_CAPTURE_STATES = ('managed', 'unmanaged')          # rows a capture would adopt


class DotfilesScreen:
    '''Link-state table over the via:dotfiles units — a skin over the dotfiles driver
    (spec_states / install / uninstall / capture, plus the per-shell glue loaders and `migrate`).'''
    def __init__(self, ctx):
        self.ctx = ctx
        self.cur = 0
        self.top = 0
        self.hscroll = 0                 # horizontal scroll across the columns (h/l)
        self.dirty = set()               # unit keys mutated here -> requeried on return to Components
        self.reload()

    def _root_label(self, root):
        '''Short label for a content root: <plugin> / <local> / <repo>, else the dir name — so
        SOURCE says WHERE the content lives, not just an ambiguous "dotfiles/".'''
        p, rp = self.ctx.paths, Path(root)
        if p.primary_dotfiles_dir is not None and rp == Path(p.primary_dotfiles_dir):
            return '<plugin>'
        if rp == p.user_dotfiles_dir:
            return '<local>'
        if rp == p.dotfiles_dir:
            return '<repo>'
        return rp.name

    def reload(self):
        from .. import actions
        self.df, self.units = actions.dotfiles_units(self.ctx)
        self.rows = []                                       # (rc, name, tgt, state, source, cap)
        for rc in self.units:
            loader = self.df._loader_shell(rc)
            if loader:                                      # a per-shell glue loader (zsh-glue/fish-glue)
                on = self.df.get_version(rc) is not None
                state = 'loader-on' if on else 'loader-off'
                src = 'rc hookup' if on else 'not hooked up'
                self.rows.append((rc, f'{loader} loader', self.df.location(rc) or '', state, src, False))
                continue
            # which specs have a real on-system file to adopt (a `managed`/`unmanaged` row is only
            # capture-ACTIONABLE if something is actually there) — capture_plan tells us per spec.
            cap = {name: (action == 'copy') for name, _d, _de, action in self.df.capture_plan(rc)}
            for name, tgt, state, src_root, src_rel, _here in self.df.spec_states(rc):
                source = f'{self._root_label(src_root)}/{src_rel}'
                self.rows.append((rc, name, tgt, state, source, cap.get(name, False)))
        self.cur = min(self.cur, max(0, len(self.rows) - 1))

    def cur_row(self):
        return self.rows[self.cur] if 0 <= self.cur < len(self.rows) else None


# Columns: COMPONENT, STATE, LINK (the ~/… symlink location on your system), SOURCE (the managed
# content it points at — the store/.cfs, or the shell rc hookup for a loader).
_DF_HEADERS = ['COMPONENT', 'STATE', 'LINK', 'SOURCE']


def _df_cells(row):
    '''The four column strings for a dotfiles row. `!` = a real on-system file we don't manage;
    `+` = a marked config with on-disk content ready to capture.'''
    rc, _name, tgt, state, source, cap = row
    mark = '!' if state == 'unmanaged' else '+' if (state == 'managed' and cap) else ' '
    return [rc.comp, f'{mark} {state}', str(tgt), source]


def _draw_dotfiles(stdscr, pal, ds, ctx, note, screen):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    pal.use_page(screen)
    if pal.gradient:
        _fill_bg(stdscr, pal, h, w)
    _draw_nav(stdscr, pal, screen, h, w)
    it, il, ih, iw = _panel(stdscr, pal, 1, 0, h - 3, w, 'dotfiles (link state)', True, h, w)
    if not ds.rows:
        _put(stdscr, it, il, _fit('   '.join(_DF_HEADERS), iw), pal.style('menu_header', it, il, h, w))
        _put(stdscr, it + 1, il, _fit('(no dotfiles in the active profiles)', iw),
             pal.style('info_dim', it + 1, il, h, w))
    else:
        # one cell-set per row; each column is sized to its longest cell so nothing is truncated —
        # horizontal scroll (h/l) reaches anything wider than the panel.
        cells_by_row = [_df_cells(r) for r in ds.rows]
        widths = [max(len(_DF_HEADERS[c]), max((len(cs[c]) for cs in cells_by_row), default=0))
                  for c in range(len(_DF_HEADERS))]
        xs, vx = [], 0
        for wd in widths:
            xs.append(vx)
            vx += wd + 2                         # two spaces between columns for breathing room
        virt_w = vx - 2
        has_hbar = virt_w > iw
        rows_h = ih - 1 - (1 if has_hbar else 0)
        ds.hscroll = max(0, min(ds.hscroll, max(0, virt_w - iw)))   # clamp: no scrolling past the end
        for hdr, vx0 in zip(_DF_HEADERS, xs):    # sticky header, scrolls horizontally with the rows
            _put_hscroll(stdscr, it, il, iw, vx0, ds.hscroll, hdr, pal.style('menu_header', it, il, h, w))
        ds.top = _scroll_top(ds.cur, ds.top, rows_h, len(ds.rows))
        for vis, i in enumerate(range(ds.top, min(len(ds.rows), ds.top + rows_h))):
            y, sel = it + 1 + vis, i == ds.cur
            if sel:
                _put(stdscr, y, il, ' ' * iw, pal.fill(y, il, h, w, selected=True))
            elem = 'label' if sel else _DF_STATE_ELEM.get(ds.rows[i][3], 'component')
            style = pal.style(elem, y, il, h, w, selected=sel)
            for cell, wd, vx0 in zip(cells_by_row[i], widths, xs):
                _put_hscroll(stdscr, y, il, iw, vx0, ds.hscroll, cell.ljust(wd), style)
        _scrollbar_v(stdscr, pal, it + 1, il + iw, rows_h, ds.top, rows_h, len(ds.rows), h, w)
        if has_hbar:
            _scrollbar_h(stdscr, pal, it + ih - 1, il, iw, ds.hscroll, iw, virt_w, h, w)

    n_unmanaged = sum(1 for r in ds.rows if r[3] == 'unmanaged')
    n_adopt = sum(1 for r in ds.rows if r[3] == 'managed' and r[5])   # managed + on-disk to capture
    status = f' {len(ds.rows)} dotfile target(s)'
    if n_unmanaged:
        status += f'   ! {n_unmanaged} unmanaged (at risk)'
    if n_adopt:
        status += f'   + {n_adopt} with on-disk config to capture (c)'
    if note:
        status += f'    {note}'
    navf = ' j/k · h/l scroll · ↵ link · c capture · m migrate · x unlink · C/L/M = all · q '
    _put(stdscr, h - 2, 0, _fit(status, w), pal.style('status_line', h - 2, 0, h, w))
    _put(stdscr, h - 1, 0, _fit(navf.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
    stdscr.refresh()


def run(ctx):
    '''Entry point used by app.cmd_tui. Returns an exit code.'''
    # First-run config generation + the interactive primary-plugin offer must happen on the MAIN
    # thread, in the normal terminal, BEFORE the worker/curses — it prompts on stdin, which would
    # collide with the background load and curses init. load_pipeline's own call then no-ops.
    ctx.ensure_user_config(offer_primary=True)
    splash_on, splash_name = _chosen_splash(ctx)
    # A PLUGIN splash must be registered before we can construct it, and the splash is chosen before
    # the worker joins — so register trusted plugin code up front, on the main thread, ONLY when a
    # plugin splash is actually selected (the built-in default needs nothing). Doing it
    # unconditionally serialized plugin loading ahead of inspection for everyone. Idempotent, so the
    # worker's own later call no-ops; skipping it here lets the worker load it lazily instead.
    from .splash import DEFAULT_SPLASH
    if splash_on and splash_name and splash_name != DEFAULT_SPLASH:
        ctx.ensure_plugin_code()
    # Inspect on a worker thread; only paint the splash if it's still going after a short beat
    # ("only when there's work" — a warm/fast run skips straight to the menu), unless forced.
    worker = _InspectWorker(ctx).start()
    if not splash_on:
        show_splash = False
    elif _splash_forced(ctx):
        show_splash = True                       # skip the timing gate entirely
    else:
        show_splash = worker.wait_settled(SPLASH_THRESHOLD)

    splash_note = None
    with curses_screen() as stdscr:
        ctx.reporter.pause()          # curses owns the screen now; don't stream to stderr
        pal = Palette(ctx.config.theme())
        if show_splash:
            import random
            from .splash import DEFAULT_SPLASH, run_splash   # importing registers the built-in default
            from ..splashes import get_splash, random_splash
            if splash_name == 'random':              # surprise me: any registered splash but the default
                splash_name = random_splash(exclude=DEFAULT_SPLASH) or DEFAULT_SPLASH
            provider = get_splash(splash_name) if splash_name else get_splash(DEFAULT_SPLASH)
            if provider is None:
                if splash_name:                  # named but not registered/trusted -> default + note
                    from .. import plugins as _pl
                    _decls = _pl.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
                    hint = _pl.splash_value_hint(splash_name, ctx.paths.plugins_dir, _decls)
                    splash_note = hint or f"splash '{splash_name}' unavailable — using '{DEFAULT_SPLASH}'"
                provider = get_splash(DEFAULT_SPLASH)   # the trust-free in-core default
            run_splash(stdscr, pal, provider, label='checking install state',
                       is_done=worker.done, frac=worker.frac, counts=worker.counts,
                       seed=random.randrange(1 << 30), linger=_splash_linger(ctx))
            # The splash allocated a run-varying number of RANDOM color slots + pairs into `pal`
            # (its water/fish palette). Rebuild the Palette so the menu starts from a clean,
            # deterministic allocator — otherwise those random colors leak into the UI and, on a
            # small-COLOR_PAIRS terminal, shift which theme colors survive every run.
            pal = Palette(ctx.config.theme())
        cfg, _requested, _units, ledger, states = worker.join()   # re-raises load errors, if any
        # Re-assert curses input modes before the interactive loop: a startup probe that briefly
        # inherited the tty (or a splash quirk) must never leave us in cooked/echo mode.
        curses.noecho()
        curses.cbreak()
        stdscr.keypad(True)
        layouts, transitive = _menu_model(cfg)
        ms = MenuState(states, layouts, transitive)
        ms.descriptions = _describe(ctx)          # {name -> desc}, cached; not touched per frame
        diags = ctx.diagnostics(states)
        note = splash_note or ''
        show_diag = False
        diag_top = 0
        show_where = False                        # `w` full-page: the complete where-report for a row
        where_lines, where_top, where_subject = [], 0, ''
        screen = 'components'
        ps = None                                 # ProfileScreen, built lazily on first visit
        cs = None                                 # ConfigScreen, built lazily on first visit
        ts = None                                 # ThemeScreen (sub-screen of Config)
        pl = None                                 # PluginScreen, built lazily on first visit
        ds = None                                 # DotfilesScreen, built lazily on first visit
        menu_dirty = False                        # a profile/config edit -> rebuild the Components tree
        pending_report = None                     # a component whose op failed this session
        pending_notes = []                         # messages saved for after the TUI exits
        while True:
            pal.new_frame()          # recycle color pairs each frame (color_pair() is 8-bit; a
            # long session or the pair-heavy Theme screen would otherwise exceed 255 pairs and wrap
            if show_where:
                where_top = _draw_where(stdscr, pal, where_lines, where_top, where_subject)
            elif show_diag:
                diag_top = _draw_diagnostics(stdscr, pal, diags, diag_top)
            elif screen == 'profiles':
                if ps is None:
                    ps = ProfileScreen(ctx)
                _draw_profiles(stdscr, pal, ps, ctx, note, screen)
            elif screen == 'plugins':
                if pl is None:
                    pl = PluginScreen(ctx)
                _draw_plugins(stdscr, pal, pl, ctx, note, screen)
            elif screen == 'dotfiles':
                if ds is None:
                    ds = DotfilesScreen(ctx)
                _draw_dotfiles(stdscr, pal, ds, ctx, note, screen)
            elif screen == 'config':
                if cs is None:
                    cs = ConfigScreen(ctx)
                _draw_config(stdscr, pal, cs, ctx, note, screen)
            elif screen == 'theme':
                if ts is None:
                    ts = ThemeScreen(ctx)
                _draw_theme(stdscr, pal, ts, ctx, note, screen)
            else:
                diag_top = _draw(stdscr, pal, ms, ctx, note, diags, False, diag_top, screen)
            note = ''
            ch = stdscr.getch()

            if show_where:                              # where overlay: scroll or exit
                if ch in (ord('w'), ord('q'), 27):
                    show_where = False
                elif ch in (ord('j'), curses.KEY_DOWN):
                    where_top += 1
                elif ch in (ord('k'), curses.KEY_UP):
                    where_top = max(0, where_top - 1)
                elif ch == ord('g'):
                    where_top = 0
                elif ch == ord('G'):
                    where_top = 10 ** 6                  # clamped by _draw_where
                continue

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
            if ch == ord('q'):                          # confirm before leaving; esc no longer quits
                if _popup_choose(stdscr, pal, 'Really quit?',
                                 [('Yes, quit', ''), ('No, keep working', '')], start=1) == 0:
                    break
                continue
            if ch == ord('!'):
                if diags:
                    show_diag, diag_top = True, 0
                continue
            if ch in KEY_TO_SCREEN:
                dest = KEY_TO_SCREEN[ch]
                if dest in IMPLEMENTED:
                    # dotfiles mutated on its page (link/capture/migrate) -> re-probe those units so
                    # Components doesn't show stale 'managed'/'adopted' after they're now linked.
                    df_dirty = ds.dirty if ds is not None else set()
                    if dest == 'components' and (menu_dirty or df_dirty):
                        try:
                            # re-resolve + re-probe newly-appearing/changed units (a membership,
                            # driver-preference or scope edit can add units or change how they
                            # resolve) plus the dotfiles units just mutated; reuses the rest and
                            # preserves selection/staging/expansion.
                            ms, cfg, ledger, states, diags = _reload(ctx, ms, set(df_dirty))
                        except Exception as e:  # noqa: BLE001 — surface, don't crash
                            note = f'reload failed: {e}'
                        menu_dirty = False
                        if ds is not None:
                            ds.dirty = set()
                    if dest == 'dotfiles' and ds is not None:  # re-read link state on entry — an
                        ds.reload()                            # install/capture elsewhere may have changed it
                    screen = dest
                else:
                    note = f'the {dest} screen is not built yet'
                continue

            # -- Profiles screen --
            if screen == 'profiles':
                from .. import actions
                if ch in (ord('j'), curses.KEY_DOWN):
                    if ps.focus == 'left':
                        ps.lcur = min(len(ps.visible_pnodes()) - 1, ps.lcur + 1)
                    else:                              # column-major grid: down = next item, wraps col
                        ps.rcur = min(len(ps.vcatalog()) - 1, ps.rcur + 1)
                elif ch in (ord('k'), curses.KEY_UP):
                    if ps.focus == 'left':
                        ps.lcur = max(0, ps.lcur - 1)
                    else:
                        ps.rcur = max(0, ps.rcur - 1)
                elif ch in (ord('\t'), curses.KEY_BTAB):
                    ps.focus = 'right' if ps.focus == 'left' else 'left'   # tab / shift-tab toggle
                elif ch in (ord('\n'), curses.KEY_ENTER) and ps.focus == 'left':
                    ps.focus = 'right'                 # a profile: open the components pane for it
                elif ch in (ord('l'), curses.KEY_RIGHT):
                    if ps.focus == 'left':
                        ps.expand_cur()                # h/l now expand/collapse the include tree
                    else:                              # next column, same row (clamped)
                        ps.rcur = min(len(ps.vcatalog()) - 1, ps.rcur + ps.rrows)
                elif ch in (ord('h'), curses.KEY_LEFT):
                    if ps.focus == 'left':
                        ps.collapse_cur()              # collapse, or step to the parent profile
                    elif ps.rcur >= ps.rrows:
                        ps.rcur -= ps.rrows            # previous column
                    else:
                        ps.focus = 'left'              # leftmost column -> back to the profiles pane
                elif ch == ord('*') and ps.focus == 'left':
                    ps.toggle_star()                   # ▸ this profile -> filter the catalog to its members
                elif ch == ord('~'):                   # within the star filter, also reveal ~-pruned comps
                    ps.show_removed = not ps.show_removed
                    ps.rcur, ps.rcol_left = 0, 0        # catalog membership changed -> reset its cursor
                elif ch == ord('g'):
                    setattr(ps, 'lcur' if ps.focus == 'left' else 'rcur', 0)
                elif ch == ord('G'):
                    if ps.focus == 'left':
                        ps.lcur = max(0, len(ps.visible_pnodes()) - 1)
                    else:
                        ps.rcur = max(0, len(ps.vcatalog()) - 1)
                elif ch == ord('F'):                   # FILTER the focused pane (live; narrows)
                    if ps.focus == 'left':
                        _filter_edit(stdscr, ps.pfilter, ps.set_pfilter,
                                     lambda: _draw_profiles(stdscr, pal, ps, ctx, note, screen))
                    else:
                        _filter_edit(stdscr, ps.cfilter, ps.set_cfilter,
                                     lambda: _draw_profiles(stdscr, pal, ps, ctx, note, screen))
                elif ch == ord('A'):                   # faceted attr filter over the catalog (kind)
                    res = _attr_filter_modal(stdscr, pal, ps.attr_inc, ps.attr_exc)
                    if res is not None:
                        ps.attr_inc, ps.attr_exc = res
                        ps.rcur, ps.rcol_left = 0, 0   # catalog membership changed -> reset its cursor
                elif ch == ord('/'):                   # fuzzy FIND in the focused pane: jump cursor
                    rdraw = lambda: _draw_profiles(stdscr, pal, ps, ctx, note, screen)
                    if ps.focus == 'left':
                        _find_edit(stdscr, [nd[0] for nd in ps.visible_pnodes()], ps.lcur,
                                   lambda i: setattr(ps, 'lcur', i), rdraw)
                    else:
                        _find_edit(stdscr, list(ps.vcatalog()), ps.rcur,
                                   lambda i: setattr(ps, 'rcur', i), rdraw)
                elif ch == ord('a') and ps.focus == 'left':
                    prof = ps.cur_profile()
                    if prof:
                        try:
                            changed, _lbl = actions.set_profile_active(ctx, prof,
                                                                       prof not in ps.active)
                            ps.reload()
                            menu_dirty = menu_dirty or changed
                            note = (f'{prof} {"activated" if prof in ps.active else "deactivated"}'
                                    if changed else 'no change')
                        except Exception as e:  # noqa: BLE001 — surface, don't crash
                            note = f'edit failed: {e}'
                elif ch == ord('n'):                       # new profile (any focus)
                    nm = _input_box(stdscr, pal, 'new profile name')
                    if nm and nm.strip():
                        try:
                            changed, lbl = actions.add_profile(ctx, nm.strip())
                            if changed:
                                ps.pfilter = ''        # clear any filter so the new profile is visible
                            ps.reload()
                            names = [nd[0] for nd in ps.visible_pnodes()]
                            if changed and nm.strip() in names:
                                ps.lcur, ps.focus = names.index(nm.strip()), 'left'
                            menu_dirty = menu_dirty or changed
                            note = f'created "{nm.strip()}" ({lbl})' if changed else lbl
                        except Exception as e:  # noqa: BLE001 — surface, don't crash
                            note = f'add failed: {e}'
                elif ch == ord('d') and ps.focus == 'left':  # delete the selected profile (confirm)
                    prof = ps.cur_profile()
                    if prof:
                        idx = _popup_choose(stdscr, pal, f'delete profile "{prof}"?',
                                            [('cancel', ''), ('delete', '')], 0)
                        if idx == 1:
                            try:
                                changed, note = actions.remove_profile(ctx, prof)
                                ps.reload()
                                ps.lcur = min(ps.lcur, max(0, len(ps.visible_pnodes()) - 1))
                                menu_dirty = menu_dirty or changed
                            except Exception as e:  # noqa: BLE001 — surface, don't crash
                                note = f'remove failed: {e}'
                elif ch == ord('+') and ps.focus == 'left':  # include another profile (+other)
                    prof = ps.cur_profile()
                    others = [p for p in ps.profiles if p != prof]
                    if prof and others:
                        inc = ctx.config.profile_includes(prof)
                        opts = [(p, '[included]' if p in inc else '') for p in others]
                        idx = _popup_choose(stdscr, pal, f'include in "{prof}" (toggle +profile)', opts, 0)
                        if idx is not None:
                            other = others[idx]
                            try:
                                changed, note = actions.set_profile_include(ctx, prof, other,
                                                                            other not in inc)
                                ps.reload()
                                menu_dirty = menu_dirty or changed
                            except Exception as e:  # noqa: BLE001 — surface, don't crash
                                note = f'include failed: {e}'
                elif ch == ord('m') and ps.focus == 'right':
                    vcat = ps.vcatalog()
                    if vcat:                               # pin the selected component's install method
                        name = vcat[ps.rcur]
                        changed, note, deferred = _pick_method_name(stdscr, pal, ctx, name)
                        if deferred:
                            pending_notes.append(deferred)
                        if changed:
                            ctx.invalidate()               # re-read so the new [via] pin shows
                            ps._res.pop(name, None)        # its resolution changed -> drop the stale entry
                            ps.reload()
                            menu_dirty = True
                elif ch in (ord(' '), ord('\n'), curses.KEY_ENTER) and ps.focus == 'right':
                    prof = ps.cur_profile()
                    vcat = ps.vcatalog()
                    if prof and vcat:
                        name = vcat[ps.rcur]
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

            # -- Dotfiles screen --
            if screen == 'dotfiles':
                row = ds.cur_row()          # (rc, name, target, state, source, capturable)
                try:
                    if ch in (ord('j'), curses.KEY_DOWN):
                        ds.cur = min(len(ds.rows) - 1, ds.cur + 1)
                    elif ch in (ord('k'), curses.KEY_UP):
                        ds.cur = max(0, ds.cur - 1)
                    elif ch in (ord('h'), curses.KEY_LEFT):   # horizontal scroll across the columns
                        ds.hscroll = max(0, ds.hscroll - 4)
                    elif ch in (ord('l'), curses.KEY_RIGHT):
                        ds.hscroll += 4                       # clamped to the content width in _draw
                    elif ch == ord('g'):
                        ds.cur = 0
                    elif ch == ord('G'):
                        ds.cur = max(0, len(ds.rows) - 1)
                    elif ch in (ord('\n'), curses.KEY_ENTER) and row:   # link (clobber-proof;
                        with suspended(stdscr):                          # refuses over a real file)
                            res = ds.df.install(row[0])
                        ds.dirty.add(row[0].key)
                        ds.reload()
                        note = (f'{row[0].comp}: {res.output().strip()}'
                                if res is not None and not res.ok else f'linked {row[0].comp}')
                    elif ch == ord('x') and row:            # unlink (restores any backup)
                        with suspended(stdscr):
                            ds.df.uninstall(row[0])
                        ds.dirty.add(row[0].key)
                        ds.reload()
                        note = f'unlinked {row[0].comp}'
                    elif ch == ord('c') and row:            # capture: adopt this row's on-system content
                        done = ds.df.capture(row[0], force=False)
                        ds.dirty.add(row[0].key)
                        ds.reload()
                        note = (f'captured {len(done)} target(s) for {row[0].comp}'
                                if done else f'nothing to capture for {row[0].comp}')
                    elif ch == ord('C'):                    # capture ALL with on-disk config to adopt
                        total = sum(len(ds.df.capture(rc, force=False)) for rc in ds.units)
                        ds.dirty.update(rc.key for rc in ds.units)
                        ds.reload()
                        note = (f'captured {total} target(s) across all dotfiles'
                                if total else 'nothing on-disk to capture')
                    elif ch == ord('L'):                    # link ALL captured-but-unlinked (adopted)
                        pend = {r[0].key: r[0] for r in ds.rows if r[3] == 'adopted'}
                        with suspended(stdscr):
                            for rc in pend.values():
                                ds.df.install(rc)
                        ds.dirty.update(pend)
                        ds.reload()
                        note = (f'linked {len(pend)} captured dotfile(s)'
                                if pend else 'nothing captured-but-unlinked')
                    elif ch in (ord('m'), ord('M')):        # migrate: re-point repo-links, move glue to
                        import types as _types                # conf.d, clear dead links (preview+confirm).
                        from .. import app as _app            # lowercase = this row's component; upper = all
                        only = ({row[0].comp} if ch == ord('m') and row else None)
                        with suspended(stdscr):
                            _app.cmd_dotfiles_migrate(ctx, _types.SimpleNamespace(yes=False, only=only))
                            try:
                                input('\n(press Enter to return) ')
                            except EOFError:
                                pass
                        ds.dirty.update(r[0].key for r in ds.rows
                                        if only is None or r[0].comp in only)
                        ds.reload()
                        note = f'migrate {row[0].comp if only else "(all)"}: done'
                except Exception as e:  # noqa: BLE001 — surface, don't crash
                    note = f'error: {e}'
                continue

            # -- Plugins screen (git ops run under `suspended` so their output owns the terminal) --
            if screen == 'plugins':
                from .. import actions, plugins
                row = pl.cur_row()
                try:
                    if pl.focus == 'diff' and pl.diff_key is None:
                        pl.load_diff()                         # remote-ref landed -> fetch it now
                    # -- focus + navigation (focus-aware j/k/h/l/g/G) --
                    if ch == ord('\t'):                        # Tab: table→diff, then file→file, then →table
                        if pl.focus == 'table':
                            pl.focus, pl.dfile = 'diff', 0
                            pl.load_diff()
                        elif pl.dfile + 1 < len(pl.diff_files):
                            pl.dfile, pl.dtop, pl.dhscroll = pl.dfile + 1, 0, 0
                        else:
                            pl.focus = 'table'
                    elif ch == curses.KEY_BTAB:                # Shift-Tab: reverse
                        if pl.focus == 'table':
                            pl.focus = 'diff'
                            pl.load_diff()
                            pl.dfile = max(0, len(pl.diff_files) - 1)
                        elif pl.dfile > 0:
                            pl.dfile, pl.dtop, pl.dhscroll = pl.dfile - 1, 0, 0
                        else:
                            pl.focus = 'table'
                    elif ch in (ord('j'), curses.KEY_DOWN):
                        if pl.focus == 'diff':
                            pl.dtop += 1
                        else:
                            pl.cur = min(len(pl.rows) - 1, pl.cur + 1); pl._invalidate_diff()
                    elif ch in (ord('k'), curses.KEY_UP):
                        if pl.focus == 'diff':
                            pl.dtop = max(0, pl.dtop - 1)
                        else:
                            pl.cur = max(0, pl.cur - 1); pl._invalidate_diff()
                    elif ch in (ord('l'), curses.KEY_RIGHT):
                        if pl.focus == 'diff':
                            pl.dhscroll += 4
                        else:
                            pl.hscroll += 6
                    elif ch in (ord('h'), curses.KEY_LEFT):
                        if pl.focus == 'diff':
                            pl.dhscroll = max(0, pl.dhscroll - 4)
                        else:
                            pl.hscroll = max(0, pl.hscroll - 6)
                    elif ch == ord('g'):
                        if pl.focus == 'diff':
                            pl.dtop = 0
                        else:
                            pl.cur = 0; pl._invalidate_diff()
                    elif ch == ord('G'):
                        if pl.focus == 'diff':
                            pl.dtop = 10 ** 6                   # clamped in the draw
                        else:
                            pl.cur = max(0, len(pl.rows) - 1); pl._invalidate_diff()
                    # -- actions --
                    elif ch == ord('a'):
                        src, replace = _input_box(
                            stdscr, pal, 'add plugin — source (github:owner/repo)', '',
                            toggle=('replace an existing plugin of the same name (retarget)', False))
                        if src and src.strip():
                            with suspended(stdscr):
                                _ok, msg, _r = actions.plugin_add(ctx, src.strip(), replace=replace)
                            pl.reload()
                            menu_dirty = True
                            note = msg.split('\n')[0]
                    elif ch == ord('x') and row:
                        _ok, note = actions.plugin_remove(ctx, row['name'])
                        pl.reload()
                        menu_dirty = True
                    elif ch == ord('s') and row:
                        tgt = [t['decl'] for t in pl.tree
                               if plugins.dir_name(t['decl']['source']) == plugins.dir_name(row['source'])]
                        with suspended(stdscr):
                            actions.plugin_sync(ctx, tgt)
                        pl.reload()
                        menu_dirty = True          # new data/drivers on disk -> rebuild Components
                        note = f'synced {row["name"]}'
                    elif ch == ord('S'):
                        with suspended(stdscr):
                            actions.plugin_sync(ctx, plugins.declared(ctx.paths.user_config_file))
                        pl.reload()
                        menu_dirty = True          # new data/drivers on disk -> rebuild Components
                        note = 'synced all'
                    elif ch == ord('b') and row:
                        with suspended(stdscr):
                            _ok, msg, _r = actions.plugin_bless(ctx, row['source'])
                        pl.reload()
                        menu_dirty = True
                        note = msg
                    elif ch == ord('B'):
                        _ok, note = actions.plugin_unbless(ctx)
                        pl.reload()
                        menu_dirty = True
                    elif ch == ord('u') and row:               # update this plugin to its latest ref
                        with suspended(stdscr):
                            _ok, msg, _r = actions.plugin_update(ctx, row['name'], latest=True)
                        pl.reload()
                        menu_dirty = menu_dirty or _ok
                        note = msg
                    elif ch == ord('U'):                       # update ALL to latest tag / main|master
                        with suspended(stdscr):
                            rows_ = actions.plugin_update_all(ctx, latest=True)
                        pl.reload()
                        menu_dirty = True
                        failed = [s for s, ok, _m in rows_ if not ok]
                        note = f'updated {len(rows_) - len(failed)}/{len(rows_)} to latest' + (
                            f' ({len(failed)} failed)' if failed else '')
                    elif ch == ord('t') and row:               # trust TOGGLE for this code plugin
                        if row['code_state'] == 'trusted':
                            _ok, note = actions.plugin_untrust(ctx, row['name'])
                        else:
                            _ok, note = actions.plugin_trust(ctx, row['name'])
                        pl.reload()
                        menu_dirty = menu_dirty or _ok
                    elif ch == ord('T'):                       # trust ALL currently-untrusted
                        _n, note = actions.plugin_trust_all(ctx)
                        pl.reload()
                        menu_dirty = menu_dirty or bool(_n)
                    elif ch == ord('v') and row:               # set the git ref (version/branch/tag)
                        ref = _input_box(stdscr, pal, f'{row["name"]} — set ref (tag/branch/sha)', '')
                        if ref and ref.strip():
                            with suspended(stdscr):
                                _ok, msg, _r = actions.plugin_update(ctx, row['name'], ref.strip())
                            pl.reload()
                            menu_dirty = True
                            note = msg
                except Exception as e:  # noqa: BLE001 — surface, don't crash
                    note = f'error: {e}'
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
                elif ch == ord('t'):
                    screen = 'theme'
                elif ch == ord('m'):                    # move this setting local <-> primary
                    key = cs.keys[cs.cur]
                    try:
                        ok, msg = actions.move_config_setting(ctx, key)
                        note = msg
                        if ok:
                            cs.reload()
                            menu_dirty = True
                    except Exception as e:  # noqa: BLE001 — surface, don't crash
                        note = f'move failed: {e}'
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
                        elif key == 'scope':                # scope: user (default) / system / unset
                            cur_idx = {'user': 0, 'system': 1}.get(info['value'], 2)
                            idx = _popup_choose(stdscr, pal, key,
                                                [('user', '(default)'), ('system', ''),
                                                 ('unset', '(→ user)')], cur_idx)
                            if idx is not None:
                                actions.set_config_setting(ctx, key, [['user'], ['system'], []][idx])
                                note = f'{key} set'
                                cs.reload()
                                menu_dirty = True
                        elif key == 'splash':               # off / built-in / a plugin provider
                            from ..splashes import splash_names, _BUILTIN_SPLASH_NAMES
                            from .splash import DEFAULT_SPLASH
                            from .. import plugins as _pl
                            _decls = _pl.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
                            prov2plug = _pl.splash_plugins(ctx.paths.plugins_dir, _decls)

                            def _tag(n):                    # show WHICH plugin provides a splash
                                return ('(built-in)' if n in _BUILTIN_SPLASH_NAMES
                                        else prov2plug.get(n, '(plugin)'))
                            opts = ([('off', '(no animation)'), ('random', '(any installed splash)')]
                                    + [(n, _tag(n)) for n in splash_names()])
                            names = [o[0] for o in opts]
                            cur = info['value']
                            cur = _pl.resolve_splash_value(cur, ctx.paths.plugins_dir, _decls) if isinstance(cur, str) else cur
                            cur_idx = (0 if isinstance(cur, str) and cur.lower() in ('off', 'false', 'no')
                                       else names.index(cur) if cur in names
                                       else names.index(DEFAULT_SPLASH) if cur in (None, 'default')
                                       and DEFAULT_SPLASH in names else 0)
                            idx = _popup_choose(stdscr, pal, key, opts, cur_idx)
                            if idx is not None:
                                val = names[idx]
                                # picking the built-in default clears the setting (tracks the default)
                                actions.set_config_setting(ctx, key, [] if val == DEFAULT_SPLASH else [val])
                                note = f'{key} = {val}'
                                cs.reload()
                        elif info['kind'] == 'scalar':      # any other scalar -> text input
                            new = _input_box(stdscr, pal, f'{key}  (empty clears)',
                                             str(info['value'] or ''))
                            if new is not None:
                                v = new.strip()
                                actions.set_config_setting(ctx, key, [v] if v else [])
                                note = f'{key} {"set" if v else "cleared"}'
                                cs.reload()
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
                        elif info['kind'] == 'dir':         # an install-layout path -> text input
                            new = _input_box(stdscr, pal, f'{key}  (path; empty = default/env)',
                                             str(info['value'] or ''))
                            if new is not None:
                                v = new.strip()
                                actions.set_config_setting(ctx, key, [v] if v else [])
                                note = f'{key} {"set" if v else "cleared"}'
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

            # -- Theme editor (sub-screen of Config); edits re-instantiate pal for live preview --
            if screen == 'theme':
                from .. import actions
                from .theme import ALL_PAGES
                try:
                    page = ALL_PAGES[ts.page]
                    if ch in (ord('\t'), curses.KEY_BTAB):
                        ts.focus = 'roles' if ts.focus == 'map' else 'map'    # toggle the two lists
                    elif ch in (ord('h'), ord('l'), curses.KEY_LEFT, curses.KEY_RIGHT):
                        left = ch in (ord('h'), curses.KEY_LEFT)
                        if ts.focus == 'map' and ts.map_ncols > 1:            # move between columns
                            step = ts.map_rows_per_col
                            ts.map_cur = (max(0, ts.map_cur - step) if left
                                          else min(len(ts.map_names) - 1, ts.map_cur + step))
                        else:
                            ts.focus = 'roles' if ts.focus == 'map' else 'map'   # else cross panels
                    elif ord('a') <= ch <= ord('f'):
                        ts.page = min(len(ALL_PAGES) - 1, ch - ord('a'))      # cycle the sample page
                    elif ch in (ord('j'), curses.KEY_DOWN):
                        if ts.focus == 'map':
                            ts.map_cur = min(len(ts.map_names) - 1, ts.map_cur + 1)
                        else:
                            ts.role_cur = min(len(ts.role_list()) - 1, ts.role_cur + 1)
                    elif ch in (ord('k'), curses.KEY_UP):
                        if ts.focus == 'map':
                            ts.map_cur = max(0, ts.map_cur - 1)
                        else:
                            ts.role_cur = max(0, ts.role_cur - 1)
                    elif ch == ord('g'):
                        setattr(ts, 'map_cur' if ts.focus == 'map' else 'role_cur', 0)
                    elif ch == ord('G'):
                        if ts.focus == 'map':
                            ts.map_cur = max(0, len(ts.map_names) - 1)
                        else:
                            ts.role_cur = max(0, len(ts.role_list()) - 1)

                    # -- color-map edits --
                    elif ts.focus == 'map' and ch in (ord(' '), ord('\n'), curses.KEY_ENTER):
                        from .theme import parse_color
                        name = ts.cur_color()
                        cur = _hex(ts.colors.get(name, (235, 235, 235)))
                        new = _input_box(stdscr, pal, f'color {name}  (now {cur} → #rrggbb)', '')
                        if new and new.strip():
                            if parse_color(new.strip()) is None:
                                note = f'invalid color: {new.strip()}'          # reject, don't store
                            else:
                                actions.set_theme_value(ctx, f'colors.{name}', new.strip())
                                pal = Palette(ctx.config.theme())
                                note = f'{name} = {new.strip()}'
                    elif ts.focus == 'map' and ch == ord('n'):
                        from .theme import parse_color
                        nm = _input_box(stdscr, pal, 'new color name', '')
                        if nm and nm.strip():
                            nm = nm.strip().replace(' ', '_')
                            hexv = _input_box(stdscr, pal, f'{nm}  (#rrggbb)', '#cccccc')
                            if hexv is None or parse_color(hexv.strip()) is None:
                                note = f'invalid color — {nm} not added'
                            else:
                                actions.set_theme_value(ctx, f'colors.{nm}', hexv.strip())
                                pal = Palette(ctx.config.theme())
                                ts.reload()
                                if nm in ts.map_names:
                                    ts.map_cur = ts.map_names.index(nm)
                                note = f'added color {nm}'
                    elif ts.focus == 'map' and ch in (ord('r'), ord('x')):
                        name = ts.cur_color()
                        if ts.color_override(name) is None:
                            note = f'{name} is a built-in color (nothing to remove)'
                        else:
                            actions.set_theme_value(ctx, f'colors.{name}', None)
                            pal = Palette(ctx.config.theme())
                            ts.reload()
                            note = f'{name} reset to default'

                    # -- gradient endpoints (single-color pseudo-roles) --
                    elif (ts.focus == 'roles' and str(ts.cur_role()).startswith('@grad')
                          and ch in (ord(' '), ord('\n'), curses.KEY_ENTER, ord('r'), ord('x'),
                                     ord('B'), ord('o'), ord('u'), ord('v'))):
                        which = 'from' if ts.cur_role() == '@grad_from' else 'to'
                        if ch in (ord(' '), ord('\n'), curses.KEY_ENTER):
                            cur = ts.grad_ref(which)
                            new = _input_box(stdscr, pal,
                                             f'{page} · gradient {which}  (now {cur} → map name or #hex)',
                                             '', complete=ts.map_names)
                            if new and new.strip():
                                if not _valid_ref(new, ts.map_names):
                                    note = f'invalid color/ref: {new.strip()}'
                                else:
                                    actions.set_theme_value(ctx, f'pages.{page}.gradient.{which}', new.strip())
                                    pal = Palette(ctx.config.theme())
                                    note = f'gradient {which} = {new.strip()}'
                        elif ch in (ord('r'), ord('x')):
                            if ts.grad_override(which) is None:
                                note = f'gradient {which} is default on {page} (nothing to reset)'
                            else:
                                actions.set_theme_value(ctx, f'pages.{page}.gradient.{which}', None)
                                pal = Palette(ctx.config.theme())
                                note = f'gradient {which} reset to default on {page}'
                        else:                                     # B/o/u/v — endpoints are one color
                            note = 'gradient endpoints have no bg or effects'

                    # -- per-page role edits --
                    elif ts.focus == 'roles' and ch in (ord(' '), ord('\n'), curses.KEY_ENTER):
                        role = ts.cur_role()
                        cur = _ref_str(ts.role_ref(role).get('fg'))
                        new = _input_box(stdscr, pal, f'{page} · {role} · fg  (now {cur} → map name or #hex)',
                                         '', complete=ts.map_names)
                        if new and new.strip():
                            if not _valid_ref(new, ts.map_names):
                                note = f'invalid color/ref: {new.strip()}'
                            else:
                                actions.set_theme_value(ctx, f'pages.{page}.{role}.fg', new.strip())
                                pal = Palette(ctx.config.theme())
                                note = f'{role} fg = {new.strip()}'
                    elif ts.focus == 'roles' and ch == ord('B'):
                        role = ts.cur_role()
                        cur = _ref_str(ts.role_ref(role).get('bg'))
                        new = _input_box(stdscr, pal, f'{page} · {role} · bg  (now {cur} → name/#hex, empty clears)',
                                         '', complete=ts.map_names)
                        if new is not None:
                            if new.strip() and not _valid_ref(new, ts.map_names):
                                note = f'invalid color/ref: {new.strip()}'
                            else:
                                actions.set_theme_value(ctx, f'pages.{page}.{role}.bg', new.strip() or None)
                                pal = Palette(ctx.config.theme())
                                note = f'{role} bg {"set" if new.strip() else "cleared"}'
                    elif ts.focus == 'roles' and ch in (ord('o'), ord('u'), ord('v')):
                        role = ts.cur_role()
                        attr = {'o': 'bold', 'u': 'underline', 'v': 'reverse'}[chr(ch)]
                        on = not bool(ts.role_style(role).get(attr))
                        actions.set_theme_value(ctx, f'pages.{page}.{role}.{attr}', on)
                        pal = Palette(ctx.config.theme())
                        note = f'{role} {attr} {"on" if on else "off"}'
                    elif ts.focus == 'roles' and ch in (ord('r'), ord('x')):
                        role = ts.cur_role()
                        if ts.role_override(role) is None:
                            note = f'{role} is default on {page} (nothing to reset)'
                        else:
                            actions.set_theme_value(ctx, f'pages.{page}.{role}', None)
                            pal = Palette(ctx.config.theme())
                            ts.reload()
                            note = f'{role} reset to default on {page}'

                    elif ch == ord('p'):                          # from/to now live in the role list
                        on = not ts.page_gradient_enabled(page)
                        actions.set_theme_value(ctx, f'pages.{page}.gradient.enabled', on)
                        pal = Palette(ctx.config.theme())
                        note = f'{page} gradient {"on" if on else "off"}'
                    elif ch == ord('D'):                          # copy this page's look onto another
                        others = [p for p in ALL_PAGES if p != page]
                        di = _popup_choose(stdscr, pal, f'copy {page}’s theme onto…',
                                           [(p, '') for p in others], 0)
                        if di is not None:
                            ok, label = actions.copy_page_theme(ctx, page, others[di])
                            if ok:
                                pal = Palette(ctx.config.theme())
                                note = f'copied {page} → {others[di]}'
                            else:
                                note = label
                    elif ch == ord('s'):
                        # Live edits already persist to your primary/local, WYSIWYG. `s` is only for
                        # deliberate FULL-SNAPSHOT saves: export a shareable pack, or promote the
                        # complete look into your primary (absolute — overrides theme plugins).
                        prim = actions.primary_theme_target(ctx)             # primary name, or None
                        opts = [('export theme pack…', 'export')]
                        if prim:
                            opts.append((f'promote full theme → primary ({prim})', 'promote'))
                        idx = _popup_choose(stdscr, pal, 'save theme',
                                            [(lbl, '') for lbl, _ in opts], 0)
                        if idx is not None and opts[idx][1] == 'promote':
                            ci = _popup_choose(stdscr, pal,
                                               'promote pins the FULL look into the primary (theme '
                                               'plugins won\'t show through) — continue?',
                                               [('promote', ''), ('cancel', '')], 1)
                            if ci == 0:
                                ok, label = actions.save_theme_to_primary(ctx)
                                pal = Palette(ctx.config.theme())
                                note = f'promoted full theme → {label}' if ok else label
                            else:
                                note = 'promote cancelled'
                        elif idx is not None:                                # export a standalone pack
                            nm = _input_box(stdscr, pal, 'export theme pack — name', '')
                            if nm and nm.strip():
                                nm = nm.strip()
                                _pdir, existed = actions.save_theme_plugin(ctx, nm)
                                if existed:
                                    oi = _popup_choose(stdscr, pal, f'{nm} exists — overwrite?',
                                                       [('overwrite', ''), ('cancel', '')], 1)
                                    if oi == 0:
                                        actions.save_theme_plugin(ctx, nm, force=True)
                                        note = f'exported theme pack {nm} (overwritten)'
                                    else:
                                        note = 'export cancelled'
                                else:
                                    note = f'exported theme pack {nm}'
                    elif ch == ord('L'):
                        names = actions.theme_plugins(ctx)
                        if names:
                            idx = _popup_choose(stdscr, pal, 'load theme', [(n, '') for n in names], 0)
                            if idx is not None:
                                actions.load_theme(ctx, names[idx])
                                pal = Palette(ctx.config.theme())
                                note = f'loaded {names[idx]}'
                        else:
                            note = 'no theme plugins saved yet (s to save one)'
                except Exception as e:  # noqa: BLE001 — surface, don't crash
                    note = f'error: {e}'
                continue

            # -- Components screen --
            if ch in (ord('j'), curses.KEY_DOWN):
                ms.move(1)
            elif ch in (ord('k'), curses.KEY_UP):
                ms.move(-1)
            elif ch == ord('g'):
                ms.go_top()
            elif ch == ord('G'):
                ms.go_bottom()
            elif ch == ord('w'):                     # full-page `where`: the complete graph for this row
                _wname = _row_component(ms.cur())
                if _wname:
                    from ..app import where_report
                    where_lines = where_report(ctx, _wname) or [f'{_wname}: nothing to show']
                    where_subject, where_top, show_where = _wname, 0, True
            elif ch == ord('F'):                     # live substring FILTER over the tree (narrows)
                _filter_edit(stdscr, ms.filter, ms.set_filter,
                             lambda: _draw(stdscr, pal, ms, ctx, note, diags, False, diag_top, screen))
            elif ch == ord('/'):                     # fuzzy FIND: jump the cursor to the best match
                _find_edit(stdscr, [n.label for n in ms.rows], ms.cursor,
                           lambda i: setattr(ms, 'cursor', i),
                           lambda: _draw(stdscr, pal, ms, ctx, note, diags, False, diag_top, screen))
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
            elif ch == ord('m'):                           # unified: pick an install method OR a provider
                changed, note, deferred = _pick_choices(stdscr, pal, ms, ctx)
                if deferred:
                    pending_notes.append(deferred)
                if changed:
                    ctx.invalidate()                       # re-read config so the new pin applies
                    try:
                        # partial requery: a pin change only alters the affected component's units,
                        # so reuse every cached state and re-probe just the new ones (dirty empty).
                        # (a provider-pin can shift the closure, but _reload re-resolves regardless.)
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
            elif ch == ord('R'):               # refresh version caches + the native package index
                with suspended(stdscr):
                    print('Refreshing the package view — re-querying version sources and running the\n'
                          'package-manager index update. This takes a moment; sudo may prompt below.\n',
                          flush=True)               # up front so the slow first step doesn't look hung
                    from .. import app
                    app.cmd_refresh(ctx, None)     # apt-get update etc.; stamps the refresh time on success
                    try:
                        input('\n[Enter] to return')
                    except EOFError:
                        pass
                curses.flushinp()
                # the stamp is already written, so repaint once NOW — the staleness chip clears
                # instantly, before the (slower) re-probe of every unit's latest version below.
                _draw(stdscr, pal, ms, ctx, 'updating latest versions…', diags, False, 0, screen)
                try:                              # a fresh index changes every unit's "latest" -> re-probe all
                    ms, cfg, ledger, states, diags = _reload(ctx, ms, set(states))
                except Exception as e:  # noqa: BLE001 — surface, don't crash
                    note = f'reload failed: {e}'
                else:
                    note = 'refreshed version caches + package index'
    ctx.reporter.resume()             # back on the console (endwin has restored the terminal)
    ctx.report_session_summary(cfg, states, diags)   # -v+: leave a recap in the scrollback
    for msg in pending_notes:         # pin/promote hints held back so they don't interrupt the TUI
        print(f'configsys: {msg}')
    if pending_report:                # an op failed; its output is captured and persisted
        print(f'configsys: an op failed — run `configsys report {pending_report}` to file it '
              f'(OS + route + captured output; you approve the full text first).')
    return 0
