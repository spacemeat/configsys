'''models.py — the Components model: the MenuState tree (Node rows, staging, modes, System Updates)
and the row helpers the screen paints from (identity / methods / infoblock lines).

Split out of menu.py (review-2026-11-2 D2).
'''

from ..drivers import get_driver, scope_meta
from ..errors import ConfigError
from ..osversion import clean_version


# op -> (single-char badge, palette color, predicate on a ComponentState)
OPS = {
    # install = "make current": absent, OR present but ALSO via a stranded method (`switch` — the
    # install folds in the swap-remove of the stranded install). Never on a dangling/unmet placeholder.
    'install': ('I', 'op_install', lambda s: s.supported
                and getattr(s, 'route_status', None) not in ('dangling', 'unmet')
                and (not s.present or getattr(s, 'route_status', None) == 'switch')),
    # a LOCKED unit is never upgraded (bulk U/I skip it; a single `u` says why — review-2026-11-2 B2)
    'upgrade': ('U', 'op_upgrade', lambda s: s.supported and s.outdated and not s.locked),
    'remove':  ('X', 'op_remove',  lambda s: s.supported and s.present),
    'lock':    ('L', 'op_lock',    lambda s: s.supported and s.present and not s.locked
                                             and s.holds_version),   # not on rolling managers (pacman/apk)
    'unlock':  ('l', 'op_unlock',  lambda s: s.supported and s.locked),
    # staged only from the `v` picker (MenuState.stage_unit), never by a bulk key
    'set-version': ('V', 'op_upgrade', lambda s: s.supported and s.present),
}


_COMP_OPS = {'op-install': 'install', 'op-upgrade': 'upgrade', 'op-remove': 'remove'}   # action -> op


_REFRESH_WARN_DAYS = 30   # a package index older than this shows in warn-color on the Components header


PROFILE, COMPONENT, UNIT, LINK = 'profile', 'component', 'unit', 'link'


def _key(action, scope='components'):
    '''The key bound to `action` as a hint glyph — so a hint names YOUR `keys:` binding, never the
    shipped letter.'''
    from .paint import _keymap
    return _keymap().glyph(scope, action)


def _is_system_update(state):
    '''True for a synthetic System Updates row (bulk-action mark; applied via upgrade_all, never
    routed per-row through run_plan). None-safe (a missing state reads as not-a-system-update).'''
    comp = getattr(state, 'component', None)
    return bool(getattr(comp, 'fields', {}).get('system_update')) if comp is not None else False


def _version_text(state, field):
    '''A state's `installed_version` / `latest_version` as the TUI shows it: clean_version'd, except
    on a System Updates row, which keeps the FULL version — the change there is usually in the
    Debian revision (2.37.2-4ubuntu3.5 -> …3.6) that clean_version strips, which would read as "no
    change". None when there is no version.'''
    v = getattr(state, field)
    return v if _is_system_update(state) else clean_version(v)


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
        self.link_target = link_target   # id of the profile node this LINK jumps to
        self.parent = None               # set by _build_tree (for collapse-to-parent)
        self.children = []

    # -- aggregate state over members -------------------------------------

    @property
    def status(self):
        ms = self.members
        supported = [m for m in ms if m.supported]
        if not supported:
            # like ComponentState.status: a driver a not-yet-trusted plugin provides reads
            # 'untrusted' (fixable with `plugin trust`), not 'unsupported'. Only when EVERY
            # member is untrusted, a mix with a genuinely unsupported member stays 'unsupported'.
            if ms and all(getattr(m, 'untrusted', False) for m in ms):
                return 'untrusted'
            return 'unsupported'
        # an untrusted member carries its trust hint in `error`; that's a trust state, not a
        # failure, so it must not turn its group 'error' (the unit's own row reads 'untrusted').
        if any(m.error for m in ms if not getattr(m, 'untrusted', False)):
            return 'error'
        for rs in ('dangling', 'unmet', 'switch'):   # routing state (stranded.py) outranks versions
            if any(getattr(m, 'route_status', None) == rs for m in supported):
                return rs
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
            v = _version_text(m, 'installed_version') or '—'   # full on System Updates rows
            return f'{v} [L]' if m.locked else v            # INSTALLED and LATEST columns line up
        present = sum(1 for m in self.members if m.present)
        return f'{present}/{len(self.members)}'

    def latest_str(self):
        if self.kind == UNIT:
            m = self.members[0]
            if not m.supported:
                return '?' if m.untrusted else ''
            v = _version_text(m, 'latest_version') or '—'
            return f'{v} [R]' if m.recipe_behind else v     # [R]: a recipe pin behind upstream
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
        self.reveal = None                 # id of a just-expanded node -> reveal its subtree next draw
        self.selected = set()              # node ids
        self.staged = {}                   # unit_key -> op
        self.errors = {}                   # unit_key -> message
        self.mode = 'to-do'                # the Components view mode (M)
        self.descriptions = {}             # {component: description} cached once per load
        self._req_sig = None               # the install set this tree was built for (matrix picks)
        self._uninstall_q = frozenset()
        self._overlay_caches = {}
        self._extra_keys = set()
        self.staged_versions = {}          # unit key -> version for a staged set-version
        self._refresh()

    def adopt_view(self, old, *, errors=True, descriptions=True):
        '''Carry `old`'s VIEW onto this freshly built tree — the one place every rebuild path (_reload,
        a mode switch, the background System Updates fold) goes through, so none forgets a field
        (B16 / tui-core-03: the `F` filter and the scroll position used to vanish on their own).
        Selection / staged ops / errors keep only what still exists; expansion, filter, cursor row
        and scroll offset follow.'''
        ids = {n.id for n in self._all_nodes()}
        self.selected = {i for i in old.selected if i in ids}
        self.staged = {k: op for k, op in old.staged.items() if k in self.states}
        self.staged_versions = {k: v for k, v in (getattr(old, 'staged_versions', None) or {}).items()
                                if self.staged.get(k) == 'set-version'}
        if errors:
            self.errors = {k: e for k, e in old.errors.items() if k in self.states}
        if descriptions:
            self.descriptions = getattr(old, 'descriptions', {})
        expanded = {n.id for n in old._all_nodes() if n.expandable and n.expanded}
        for n in self._all_nodes():
            if n.expandable:
                n.expanded = n.id in expanded
        self.filter = getattr(old, 'filter', '')
        self.top = getattr(old, 'top', 0)
        if getattr(old, '_req_sig', None) is not None:
            self._req_sig = old._req_sig
        self._uninstall_q = getattr(old, '_uninstall_q', frozenset())
        self._refresh(keep_id=(old.cur().id if old.cur() else None))
        return self

    def _invert(self):
        name_units = {}
        for key, st in self.states.items():
            # glue/dotfiles companions are managed on the Glue/Dotfiles screens. A companion pulled in
            # by a suggests/requires carries requested_as={parent}, so it would otherwise nest under
            # its parent component as a dependency row (and be staged when the parent is). Drop it from
            # the name->units map so it's absent from the Components tree entirely (rows AND members).
            if getattr(st.component, 'driver', '') in ('glue', 'dotfiles'):
                continue
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
        # profiles reached via a `+include` (so `p:<ref>` is a link target) — used to drop an
        # excluded subprofile's now-empty top-level node without hiding a top-level profile group.
        include_targets = {ref for _p, items in self.layouts
                           for kind, ref in items if kind == 'include'}
        for profile, items in self.layouts:
            pnode = Node(PROFILE, f'p:{profile}', profile, 0, [],
                         expandable=True, expanded=True)
            for kind, name in items:
                if kind == 'include':          # a link to the top-level p:<name> node
                    members = [self.states[k] for k in self._profile_units.get(name, [])
                               if k in self.states]
                    if not members:
                        continue               # an EXCLUDED subprofile contributes no units here ->
                                               # don't show it at all (vs an OS-unsupported subprofile,
                                               # whose units ARE present, just unsupported)
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
            # a subprofile pulled in only via +include, now contributing nothing (fully excluded),
            # would render as an empty 'unsupported' top-level node — drop it. (Emptiness is computed
            # the same way as its links above, so no surviving link points at a dropped node.)
            if not pnode.members and profile in include_targets:
                continue
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

    def reveal_node(self, node):
        '''Expand every ancestor of `node` so it becomes a visible row, rebuild, and put the cursor on
        it. Used by find (`/`) to reach a component collapsed inside a tree.'''
        p = node.parent
        while p is not None:
            if p.expandable:
                p.expanded = True
            p = p.parent
        self._refresh()
        self._goto(node.id)

    def expand(self, want):
        n = self.cur()
        if n and n.expandable and n.expanded != want:
            n.expanded = want
            if want:
                self.reveal = n.id                 # reveal the opened subtree on the next draw
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
            self.reveal = n.link_target        # reveal the jumped-to profile's subtree, not just its head
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
            self.reveal = n.link_target        # reveal the jumped-to profile's subtree, not just its head
        elif n.expandable and not n.expanded:
            n.expanded = True
            self.reveal = n.id                     # reveal the opened subtree on the next draw
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
        if want:
            self.reveal = keep                     # expanding all -> reveal the cursor's subtree
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

    _OWN_ONLY_OPS = frozenset({'remove', 'lock', 'unlock'})

    def _own_members(self, node):
        '''The units a remove/lock/unlock on `node` acts on: the row's OWN units, never the shared
        dependencies its closure pulled in (curl, git, Homebrew, flatpak — review-2026-11-2 A7; the
        CLI's `remove X` / `lock X` touch only X). A unit row is its own unit; a component row is the
        units of that component (for a `parts` bundle with none of its own, the closure's roots — the
        parts, not their dependencies); a profile/link row is its components' own units. A
        dependency is acted on only from its own row.'''
        if node.kind == UNIT:
            return list(node.members)
        if node.kind == COMPONENT:
            own = [m for m in node.members if m.component.comp == node.label]
            if own:
                return own
            dep_keys = set().union(*(set(getattr(m.component, 'deps', ()) or ()) for m in node.members))
            return [m for m in node.members if m.key not in dep_keys]
        out, seen = [], set()
        for child in node.children:
            for m in self._own_members(child):
                if m.key not in seen:
                    seen.add(m.key)
                    out.append(m)
        if node.kind == LINK and not node.children:      # a link carries no children: its target's
            target = next((r for r in self.roots if r.id == node.link_target), None)
            if target is not None:
                return self._own_members(target)
        return out

    def stage(self, op):
        staged_any = False
        self.skip_note = ''                # why nothing was staged, when it was a lock (the screen shows it)
        for node in self._target_nodes():
            members = self._own_members(node) if op in self._OWN_ONLY_OPS else node.members
            for m in members:
                if (op in ('install', 'upgrade') and m.supported and m.present and m.outdated
                        and m.locked):
                    self.skip_note = (f'{m.component.comp} is locked at {m.installed_version} — '
                                      f'{_key("lock")} unlocks it first')
                if m.component.fields.get('system_update'):   # System Updates are bulk-action, not staged
                    continue
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

    def stage_all(self, op):
        '''Bulk `stage`: apply `op` to EVERY unit in the install set (not just the cursor/selection),
        with the SAME per-unit semantics as `stage` — `install` means "make current" (install if
        absent, else upgrade if outdated); `upgrade` upgrades an outdated unit. Returns count staged.
        Glue/dotfiles companions are skipped: they're hidden from this screen's tree (managed on the
        Glue/Dotfiles pages), so a bulk op must not sweep them into the staged/execute list either.
        A unit that already carries a staged op is LEFT ALONE — notably a `remove` seeded from the
        !uninstall queue (`_seed_uninstall`), which a bulk install/upgrade must never flip. And only
        TRACKED units are swept: those a pick of this machine pulled in (`requested_as` ∩ the install
        set this tree was built for, `_req_sig`) — not installed-but-untracked extras or
        !uninstall-queue entries that `states` also holds. (`_req_sig` unset = no restriction: a
        directly-constructed MenuState, e.g. in tests.)'''
        tracked = getattr(self, '_req_sig', None)
        n = 0
        for k, s in self.states.items():
            if getattr(s.component, 'driver', '') in ('glue', 'dotfiles'):   # owned by the Glue/Dotfiles screens
                continue
            if s.component.fields.get('system_update'):   # System Updates apply in bulk, never per-row
                continue
            if k in self.staged:                          # never override an explicit/seeded op
                continue
            if tracked is not None and not (set(getattr(s.component, 'requested_as', ()) or ())
                                            & set(tracked)):
                continue                                  # not part of this machine's picks
            eff = op
            if op == 'install' and not OPS['install'][2](s) and OPS['upgrade'][2](s):
                eff = 'upgrade'
            if OPS[eff][2](s):
                self.staged[k] = eff
                self.errors.pop(k, None)
                n += 1
        return n

    def stage_system_updates(self):
        '''Mark EVERY System Updates row staged (op 'upgrade') — the bulk-action mark: i/u anywhere in
        that subtree stages them all (all-or-nothing), then execute applies the managers' bulk upgrades
        (see _confirm_and_execute, which pulls these out of the per-unit plan). Returns count.'''
        n = 0
        for k, st in self.states.items():
            if _is_system_update(st):
                self.staged[k] = 'upgrade'
                self.errors.pop(k, None)
                n += 1
        return n

    def toggle_lock(self):
        '''Toggle version-lock intent on the target units (present + supported) — the selection, or
        the current row when nothing is selected. Unlocking removes a staged (requested) lock as well
        as staging an unlock for an actually-locked unit; locking removes a staged unlock as well as
        staging a lock for an unlocked unit. So one key flips both a pending request and a settled
        lock (a locked unit -> unlock). `c` (clear) drops the staged op -> back to the current on-disk
        lock state.'''
        acted = False
        for node in self._target_nodes():
            for m in self._own_members(node):              # never a shared dependency (A7)
                if not (m.supported and m.present) or m.component.fields.get('system_update'):
                    continue                                # System Updates can't be version-locked here
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
        '''Drop the staged op of every target unit. System Updates rows are all-or-nothing, like
        their staging: execute bulk-upgrades a whole manager (upgrade_all) whenever ANY of its rows
        is staged, so unstaging just some rows would leave badges that lie about what X does —
        touching any System Updates row unstages them all. Returns the count unstaged.'''
        n, su = 0, False
        for node in self._target_nodes():
            for m in node.members:
                if _is_system_update(m):
                    su = True
                    continue
                if self.staged.pop(m.key, None) is not None:
                    n += 1
        if su:
            n += self.unstage_system_updates()
        return n

    def unstage_system_updates(self):
        '''Unstage EVERY System Updates row (the bulk mark's inverse). Returns count.'''
        keys = [k for k in self.staged if _is_system_update(self.states.get(k))]
        for k in keys:
            del self.staged[k]
        return len(keys)

    def plan(self):
        return [(op, k, self.states[k].component) for k, op in sorted(self.staged.items())]

    def plan_versions(self):
        '''{unit key: version} for the staged set-version ops (run_plan's per-unit `version=`).'''
        sv = getattr(self, 'staged_versions', None) or {}
        return {k: v for k, v in sv.items() if self.staged.get(k) == 'set-version'}

    def stage_unit(self, key, op, version=None):
        '''Stage `op` on ONE unit, whatever OPS' predicates say — the `v` picker's explicit rebuild
        (an `install` of a present unit) and set-version. Returns True when staged.'''
        if key not in self.states:
            return False
        self.staged[key] = op
        if op == 'set-version':
            self.__dict__.setdefault('staged_versions', {})[key] = version
        return True

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


def _method_tags(cands, current_via, default_via, choice):
    '''Render each candidate as a display tag. The CURRENT method (what installs now) is bracketed
    `[via]`; the auto-default is flagged `via *` ONLY when you're on something else (so an unmarked-
    but-not-bracketed list means "on the natural default", and a `*` elsewhere means "you've diverged"
    — the no-surprises signal, whether the divergence is a pin or a detected install).'''
    out = []
    for c in cands:
        via = c['via']
        tag = f'[{via}]' if (choice and via == current_via) else via   # a lone method needs no marker
        if choice and via == default_via and via != current_via:
            tag += ' *'
        out.append(tag)
    return out


def _methods_line(ms, ctx):
    '''A line listing every install method eligible for the current component here — not just the
    default or the pin. The method that ACTUALLY resolves now (a pin, a detected-adopted install, or
    the auto-default) is bracketed `[via]`; when you're off the auto-default, that default is flagged
    `via *` (what unpinning would give you). Always names the method, even with one option. `v` opens
    the picker when there's a real choice (>=2).'''
    name = _row_component(ms.cur())
    if not name:
        return ''
    cands = ctx.routes.candidates(name)
    if not cands:
        return ''
    choice = len(cands) >= 2
    resolved_via = next((c['via'] for c in cands if c['default']), None)
    default_via = next((c['via'] for c in cands if c.get('auto')), resolved_via)   # unpinned auto-default
    current_via = _current_via(ms.cur(), name) or resolved_via   # what installs now (detection-aware)
    parts = _method_tags(cands, current_via, default_via, choice)
    line = f' via: {"   ".join(parts)}'
    if choice:                                               # surface the deciding rule (the "why")
        why = _why(ctx, name)
        change = f'{_key("method")} to change'
        line += f'      (default: {why} · {change})' if why else f'      ({change})'
    return line


def _why(ctx, name):
    '''The rule that picked the default method for `name` here — most-specific `when:` / `standing:` /
    driver-preference / only method — for the ambient "why" hint. '' if undecidable/unroutable.'''
    from ..resolve import ResolveError, binding_pin
    r = ctx.routes
    comp = r.components.get(name)
    if comp is None or not comp.bindings:
        return ''
    pinned = binding_pin(r.pins, name)
    try:
        rule = r.select(comp, pins=r.unpinned(name) if pinned else None).rule
    except ResolveError:
        rule = ''
    if pinned:                       # the pin decides; the rule is what the auto-default (`*`) follows
        return f'pinned to {pinned}' + (f'; * = auto by {rule}' if rule else '')
    return rule


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
        from ..resolve import ResolveError, cap_constraints, cap_names
        won = ctx.routes.select(comp).binding
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
    name = _row_component(ms.cur())
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
    parts += [f'installed: {_version_text(m, "installed_version") or "—"}',
              f'latest: {_version_text(m, "latest_version") or "—"}']
    if m.locked:
        parts.append('version-locked')
    drv = get_driver(rc.driver, ctx.runner, ctx.paths)
    loc = drv.location(rc) if drv is not None else None
    if loc:
        parts.append(f'at: {loc}')                # location now rides the same line as the versions
    if m.also_present:                            # coexisting installs via OTHER (unmanaged) methods
        from ..stranded import stranded_reasons
        strand = stranded_reasons(m)
        parts.append('also present: ' + ', '.join(
            f'{via} {ver}' + (f' (stranded — `{_key("op-install")}` swaps it out)' if (via, pkg) in strand else '')
            for via, pkg, ver in m.also_present))
    if m.recipe_behind:                           # [R]: upstream moved past what the recipe builds
        from ..installState import recipe_pin_text
        parts.append('[R] ' + recipe_pin_text(clean_version(m.latest_version),
                                              clean_version(m.upstream_version)))
    return ' ' + '   ·   '.join(parts)


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
    dep row (e.g. the `method` picker or `where` on cuda-toolkit-12 nested under blender) targets the
    dep, not the requester.
    Component-group / profile rows carry their own name in the id (`c:<profile>:<name>`).'''
    if node is None:
        return None
    if node.kind == UNIT and node.members:
        return node.members[0].component.comp
    parts = node.id.split(':')
    return parts[2] if parts[0] in ('c', 'u') and len(parts) >= 3 else None


def _describe(ctx):
    '''{component name -> one-line description}, built ONCE per menu build. `ctx.routes` is memoized
    (until `invalidate()`), but walking every component per row/per frame is still waste — cache it on
    the MenuState and look it up from the dict while painting.'''
    try:
        return {name: c.description for name, c in ctx.routes.components.items()}
    except Exception:   # noqa: BLE001 — a resolve hiccup shouldn't blank the whole screen
        return {}


def _is_companion_comp(routes, comp):
    '''True for a -dotfiles / -glue companion (attrs dotfiles/glue). These are managed on the
    Dotfiles / Glue pages, not the Components tree: a config lives there as managed/unmanaged, and
    glue is ACTIVATED (not installed) — shown in Components it would read a misleading "missing"
    (its unit has no package version). Excluding it is a VIEW filter only; the unit stays in
    `states`, so resolution / the CLI install path / execution are unaffected.'''
    o = routes.components.get(comp)
    return o is not None and bool({a.lower() for a in getattr(o, 'attrs', [])} & {'dotfiles', 'glue'})


def _group_by_owner(cfg, scope):
    '''(layouts, transitive) for a set of component names, grouped under each component's OWNING
    profile (profile_own_components — the DECLARING profile, not one that merely +includes it; the
    synthetic `!` lenses skipped), deterministic + deduped; anything in no profile falls under a
    synthetic `(other)` group.'''
    scope = set(scope)
    layouts, transitive, placed = [], {}, set()
    for p in sorted(cfg.profile_names()):
        if p.startswith('!'):                          # skip the synthetic !all / !uninstall lenses
            continue
        try:
            mem = [c for c in cfg.profile_own_components(p) if c in scope and c not in placed]
        except ConfigError:
            mem = []
        if mem:
            layouts.append((p, [('component', c) for c in mem]))
            transitive[p] = mem
            placed.update(mem)
    orphan = sorted(scope - placed)                    # in no profile
    if orphan:
        layouts.append(('(other)', [('component', c) for c in orphan]))
        transitive['(other)'] = orphan
    return layouts, transitive


COMPONENT_MODES = ('to-do', 'tracked', 'installed+tracked')   # the Components view MODE cycle


# ComponentState.status values that keep a tracked component in the to-do view: it isn't green and
# the user has something to do. Routing statuses rank ahead of missing/outdated in .status, so they
# must be listed or a stranded `switch` (whose action is `i`) would never surface by default.
# a unit in any of these needs YOUR action for the pick to be green — including `error` (a route or
# plugin problem to read on the ! page) and `untrusted` (`plugin trust`) (B16 / tui-core-04)
_TODO_STATUSES = ('missing', 'outdated', 'switch', 'unmet', 'dangling', 'error', 'untrusted')


def _components_model(ctx, cfg, states, mode, caches=None):
    '''Build (states, layouts, transitive) for the Components tree in `mode` (COMPONENT_MODES; the
    session starts in 'to-do'):
      'tracked'            — this machine's picked set (requested()).
      'installed+tracked'  — the picked set PLUS installed-but-untracked components (mapped to
                             recipes); the extras are resolved + inspected and folded into `states`.
      'to-do'              — ONLY components needing action for full green: a tracked component that
                             is missing or outdated, or whose ROUTING needs attention (`switch` —
                             installed via a method routes no longer offer, `i` swaps it; `unmet` /
                             `dangling` — no usable method here, untrack it or re-enable the driver;
                             docs/stranded-installs.md), or a staged-for-uninstall component still
                             present. Fully-green components (and thus now-empty profile groups) are omitted.
    Returns the (possibly extended) states plus the grouped layouts/transitive.'''
    tracked = set(cfg.requested())
    queue = set(cfg.uninstall_queue())
    # Drop any synthetic System Updates rows from a prior build BEFORE the mode logic runs — they
    # must never reach install_overlay / _ensure (they aren't real units). They're re-injected fresh
    # from the cached scan at the end.
    states = {k: v for k, v in states.items()
              if not getattr(v.component, 'fields', {}).get('system_update')}

    def _ensure(names):                                # inspect any names not already in `states`
        nonlocal states
        have = {st.component.comp for st in states.values()}
        missing = [n for n in names if n not in have]
        if missing:
            try:
                states = {**states, **ctx.inspect_components(missing)}
            except Exception:                          # noqa: BLE001 — never let a probe brick the view
                pass

    if mode == 'installed+tracked':
        from .. import orphans as _orph
        try:                                           # `caches` is reused across switches -> the (slow,
            installed, _orphans, _caches = _orph.install_overlay(   # subprocess-bound) driver enumerations
                ctx, {k: st.component for k, st in states.items()}, caches=caches)   # aren't re-run each time
        except Exception:                              # noqa: BLE001
            installed = set()
        extra = (installed & set(ctx.routes.components)) - tracked
        _ensure(extra)
        scope = tracked | extra
    elif mode == 'to-do':
        _ensure(queue)                                 # need install state of staged-uninstall comps
        actionable, present = {}, {}                   # per component: needs install/update? present?
        for st in states.values():
            c = st.component.comp
            todo = st.status in _TODO_STATUSES
            # per tracked NAME over every unit that groups under it — its own and the dependencies
            # pulled for it (requested_as, as the tree groups them) — so a pick whose own unit is green
            # but whose dependency is missing (`partial`) is shown, not hidden while `I` stages it
            # (glue/dotfiles companions live on their own pages — they don't make the parent to-do)
            via_pages = getattr(st.component, 'driver', '') in ('glue', 'dotfiles')
            for name in {c} | (set() if via_pages else set(getattr(st.component, 'requested_as', ()) or ())):
                actionable[name] = actionable.get(name, False) or todo
            present[c] = present.get(c, False) or st.present
        scope = {c for c in tracked if actionable.get(c)}          # tracked but not green
        scope |= {c for c in queue if present.get(c)}              # staged-uninstall, still installed
    else:                                              # 'tracked'
        scope = tracked

    scope = {c for c in scope if not _is_companion_comp(ctx.routes, c)}   # -dotfiles/-glue: their own pages
    layouts, transitive = _group_by_owner(cfg, scope)
    # Fold in the synthetic System Updates group (the whole-machine upgradable set outside picks),
    # from the cached background scan — a sibling to (other), shown in every mode. Display-only:
    # these rows can't be individually staged (bulk-action, see the screen handler).
    groups = getattr(ctx, '_sysupd_groups', None)
    if groups:
        from .. import sysupdates
        su_states, su_layouts, su_transitive = sysupdates.tree_injection(groups)
        if su_states:
            states = {**states, **su_states}
            layouts = layouts + su_layouts
            transitive = {**transitive, **su_transitive}
    return states, layouts, transitive


def _fold_system_updates(ctx, cfg, ms):
    '''Fold a freshly-landed background System Updates scan into the Components tree -> (ms, states).
    Only the TREE changes (installed state didn't), so it's rebuilt from the states already held
    (~15ms) — not _reload, which re-runs the load pipeline + diagnostics (~6s on a full machine) on the
    UI thread: the freeze right after the splash. An older scan's synthetic rows are dropped first, so
    a rescan (after a system upgrade) replaces them rather than stacking.'''
    from .. import sysupdates
    real = {k: st for k, st in ms.states.items() if not sysupdates.is_synthetic(st)}
    mode = getattr(ms, 'mode', 'to-do')
    states, layouts, transitive = _components_model(ctx, cfg, real, mode,
                                                    caches=getattr(ms, '_overlay_caches', None))
    return _rebuild_menu(ms, states, layouts, transitive, mode), states


def _rebuild_menu(old, states, layouts, transitive, mode):
    '''Rebuild a MenuState for a NEW tree (a mode switch) while preserving cursor / expansion /
    selection / staged ops / errors / descriptions from `old` — WITHOUT re-running the pipeline
    (install state is unchanged; only WHICH components are shown). The cheap counterpart to _reload.'''
    ms = MenuState(states, layouts, transitive)
    ms.mode = mode
    ms.adopt_view(old)                               # routes didn't change -> descriptions reused
    ms._overlay_caches = getattr(old, '_overlay_caches', {})
    ms._extra_keys = {k for k in getattr(old, '_extra_keys', ()) if k in states}
    return ms


def _added_extras(base, states):
    '''Unit keys `_components_model` folded into `states` beyond `base` (installed+tracked's
    installed-but-untracked extras) — synthetic System Updates rows excluded (re-injected per build).'''
    return {k for k, st in states.items() if k not in base and not _is_system_update(st)}


def _switch_mode(ctx, cfg, ms, mode):
    '''A view-MODE switch -> (new_ms, states, layouts, transitive). The installed+tracked extras are
    remembered on the MenuState (`_extra_keys`) and DROPPED from `states` when switching away — else
    they'd linger in `states` (invisible in to-do/tracked) for a later bulk op to sweep up. An extra
    carrying a staged op is kept (dropping it would silently discard what the user staged).'''
    drop = {k for k in getattr(ms, '_extra_keys', ()) if k not in ms.staged}
    base = {k: v for k, v in ms.states.items() if k not in drop}
    states, layouts, transitive = _components_model(ctx, cfg, dict(base), mode,
                                                    caches=getattr(ms, '_overlay_caches', None))
    new_ms = _rebuild_menu(ms, states, layouts, transitive, mode)
    kept = (set(getattr(ms, '_extra_keys', ())) - drop) & set(states)
    new_ms._extra_keys = kept | (_added_extras(base, states) if mode == 'installed+tracked' else set())
    return new_ms, states, layouts, transitive
