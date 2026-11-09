'''profiles.py — the Profiles browse/matrix screen as a Screen (build_vm/draw/handle).

Migrated off the monolithic menu.py painter (docs/done/d2-mvvm-plan.md), after the Plugins / Config /
Dotfiles / Glue pattern-setters. The model is the existing `menu.ProfileScreen` (profile tree +
component catalog + matrix state, the overlay/probe machinery), composed unchanged; this adds the
three MVVM seams:

- build_vm: the whole frame from the model + the frame size (review-2026-11-2 D7) — the panel
  geometry, the profile tree's visible rows (text, `~` attribution, badges), the detail box's lines
  and the catalog matrix's column spec + visible rows as positioned cells. It reads `self.model.ctx`
  (a sample overlay ctx — menu._sample_profiles_state — is honoured), runs the overlay fold and the
  coverage hint, and settles the scroll offsets (applied by commit).
- draw: paints that VM — palette concerns only (the selection fill, the dim bar of an unfocused
  cursor, reverse video on a low-colour terminal).
- handle: the former `if screen == 'profiles'` dispatch, returning an Intent (note / dirty /
  pending_notes / open_where) instead of mutating loop-scope locals. The `machine-target` branch,
  which REBOUND the loop's `ps`, rebinds `self.model` internally.
'''

import curses
from fnmatch import fnmatchcase

from .. import menu
from ..flows import _pick_method_name
from ..modals import (
    _attr_filter_modal, _component_machines_modal, _filter_edit, _find_edit, _machines_modal,
    _popup_choose)
from ..paint import (
    _busy, _fit, _page_rows, _panel, _put, _reveal_subtree, _scroll_top, _scrollbar_h,
    _scrollbar_v, _wordwrap, _wrap)
from ..panes import ProfileScreen as _ProfilesModel
from ...errors import ConfigsysError
from .base import Intent, Screen, ViewModel


class ProfilesVM(ViewModel):
    '''Everything one Profiles frame paints, settled by build_vm from the model + the frame size —
    draw decides nothing (review-2026-11-2 D7 / tui-screens-07). Geometry is in terminal cells; the
    pane contents are final text + element roles, so a test (or a Theme sample) can build one by hand.'''

    def __init__(self):
        self.prof = None           # the selected (browsed) profile, or None
        self.ltitle = 'profiles'   # left panel title (with the pane filter)
        self.ctitle = 'components' # catalog panel title (profile, filter, #sel, attr summary)
        self.status = ''           # status line WITHOUT the transient note
        self.note = ''             # the transient action note (the host supplies it; '' when none)
        self.legend1 = ''
        self.legend2 = ''
        self.nav1 = ''
        self.nav2 = ''
        self.focus = 'left'
        self.overlay = (frozenset(), {}, frozenset())   # install-axis overlay (empty unless `O` on)
        self.cur_oses = None       # the catalog cursor's component has no method here: where it has one
        # geometry
        self.top = 1               # panels start below the screen chips
        self.body_h = 1            # the panels' height (two status/legend rows + two nav rows below)
        self.lw = 16               # the profiles pane's width; the right column is the rest
        self.desc_h = 0            # the detail box's height (0 on a short terminal)
        # LEFT: the profile tree — the visible window
        self.left_rows = []        # [LeftRow]
        self.left_n = 0            # every visible tree row (for the scrollbar)
        self.ltop = 0
        self.left_max = 0          # the widest row's length (the h-scroll range)
        self.lhoff = 0             # the pane's horizontal char offset
        # RIGHT TOP: the detail box
        self.detail_title = ''
        self.detail_lines = []     # [(row inside the box, text, role)]
        # RIGHT BOTTOM: the catalog matrix
        self.cat_header = []       # [(x, text, role, bold)]
        self.cat_rows = []         # [CatRow] — the visible window
        self.cat_n = 0
        self.rtop = 0
        self.rcol_left = 0         # horizontal offset into the matrix
        self.cat_w = 0             # the matrix's virtual width
        self.shown = []            # components on screen (commit probes them)


class LeftRow:
    '''One profile-tree row: its text (twisty, `~` attributions, name, badges), whether it is the
    browsed profile, whether an excluded ancestor strikes it, and its count badges [(text, role)].'''
    __slots__ = ('text', 'cur', 'struck', 'badges')

    def __init__(self, text, cur, struck, badges):
        self.text, self.cur, self.struck, self.badges = text, cur, struck, badges


class CatRow:
    '''One catalog row: [(x, text, role, attr flag)] cells (`attr` is 'underline' / 'bold' / None),
    and whether it is the cursor row.'''
    __slots__ = ('cells', 'cur')

    def __init__(self, cells, cur):
        self.cells, self.cur = cells, cur


def _nav_strs():
    g = lambda a: menu._keymap().glyph('profiles', a)
    nav1 = (f" {g('down')}/{g('up')} move · {g('right')}/{g('left')} scroll/expand · "
            f"{g('switch-pane')} panes · {g('find')} find · {g('filter')} filter · "
            f"{g('attr-filter')} attrs · {g('machine-target')} machines · {g('where')} where ")
    nav2 = (f" {g('track-all')} track-set · {g('track-one')} track-one · {g('disp-interesting')} int · "
            f"{g('disp-seen')} seen · {g('select')} sel · {g('select-all')} all · "
            f"{g('method')} via · {g('stage-uninstall')} uninst · {g('quit')} quit ")
    return nav1, nav2


class ProfilesScreen(Screen):
    id = 'profiles'

    def __init__(self, ctx, model=None):
        self.ctx = ctx
        self.model = model if model is not None else _ProfilesModel(ctx)

    def reload(self):
        self.model.reload()

    # -- build_vm ---------------------------------------------------------

    def build_vm(self, ctx, size):
        ps = self.model
        mctx = ps.ctx                                  # the model's ctx (a sample overlay in tests)
        h, w = size
        vm = ProfilesVM()
        vm.focus = ps.focus
        prof = ps.cur_curate()
        vm.prof = prof
        vm.ltitle = 'profiles' + (f'  filter:{ps.pfilter}' if ps.pfilter else '')
        vm.ctitle = ((f'components — in "{prof}"' if prof else 'components')
                     + (f'  filter:{ps.cfilter}' if ps.cfilter else '')
                     + ('  #sel:' + str(len(ps.selected_comps)) if ps.selected_comps else '')
                     + ps.attr_summary())
        _tg = sorted(ps.targets())
        vm.status = (f' browse: {prof or "—"}    this box: {mctx.config.current_machine()}'
                     f'    targets: {", ".join(_tg) or "(none)"}')
        vm.legend1 = "inst'd  ● trk  ⊙ untrk  ◐ part  ○ no  ⮾ uninst  ⊘ n/a-here "
        vm.legend2 = "flag  ☆ int  · seen    new  ◆    machine  ● tracked  ○ not    tree  ⊙ N "
        vm.nav1, vm.nav2 = _nav_strs()
        # the work a frame needs that touches more than the model — the overlay (folds in a finished
        # async scan, may start one) and the coverage matrix for an unavailable component (cached
        # per component) — happens here, never in draw
        vm.overlay = ps.overlay()
        crows = ps._catalog_rows()                       # [(name, depth)] — parts children interleaved
        vcat = [nm for nm, _dep in crows]
        cur = vcat[ps.rcur] if vcat and 0 <= ps.rcur < len(vcat) else None
        if cur is not None and not ps.available(cur):
            vm.cur_oses = ps.available_oses(cur)

        vm.top, vm.body_h = 1, max(1, h - 5)             # TWO status/legend rows, then TWO nav rows below
        vm.lw = max(16, w // 6) + 6                      # profiles pane: narrow, leaving the grid room
        rw = w - vm.lw - 1
        vm.desc_h = 8 if vm.body_h >= 13 else 0          # one extra inner row for the "needs" line
        self._left_vm(vm, ps, mctx, vm.body_h - 2, vm.lw - 2)
        self._detail_vm(vm, ps, mctx, prof, cur, vm.desc_h - 2, rw - 2)
        self._catalog_vm(vm, ps, mctx, crows, vm.body_h - vm.desc_h - 2, rw - 2)
        return vm

    def _left_vm(self, vm, ps, ctx, lih, liw):
        '''The profile tree's visible window: each row's text, `~` attribution and badges.'''
        vnodes = ps.visible_pnodes()
        ltop = ps.ltop
        if ps.reveal is not None:                        # a just-expanded node -> reveal its subtree
            ltop = _reveal_subtree([nd[2] for nd in vnodes], [nd[1] for nd in vnodes], ps.reveal,
                                   ltop, lih)
        ltop = _scroll_top(ps.lcur, ltop, max(1, lih), len(vnodes))
        lmax = 0
        for i in range(ltop, min(len(vnodes), ltop + max(1, lih))):
            name, depth, key, expandable, expanded, kind = vnodes[i][:6]
            exp = '▾' if expanded else ('▹' if expandable else ' ')
            scope = '▸' if i == ps.lcur else ' '         # marks the profile the catalog is showing
            prefix = list(f'{scope}{"  " * depth}{exp}')
            # Exclusion attribution: a `~` in the at-fault ancestor's status-glyph column.
            struck = False
            for ai, anc in enumerate(key.split('\x00')[:-1]):     # ancestors; path index == their depth
                try:
                    if name in ctx.config.profile_excludes(anc):
                        col = 2 + 2 * ai
                        if 0 <= col < len(prefix):
                            prefix[col] = '~'
                        struck = True
                except Exception:                                  # noqa: BLE001 — a bad profile marks nothing
                    pass
            nnew = ps.profile_new_count(name)
            nint = ps.profile_interesting_count(name)
            nunt = ps.profile_untracked_count(name)       # installed here but not tracked (claimable)
            badges = [(t, role) for t, role in ((f'⁺{nnew}' if nnew else '', 'menu_new'),
                                                (f'☆ {nint}' if nint else '', 'link'),
                                                (f'⊙ {nunt}' if nunt else '', 'installed')) if t]
            disp = f'+{name}' if kind == 'include' else name  # `+`-mark a live include child
            text = f'{"".join(prefix)} {disp}' + ''.join(f'  {t}' for t, _r in badges)
            lmax = max(lmax, len(text))
            vm.left_rows.append(LeftRow(text, i == ps.lcur, struck, badges))
        vm.left_n, vm.ltop, vm.left_max = len(vnodes), ltop, lmax
        lhmax = max(0, lmax - liw)                       # clamp target for ←/→ (the handler reads it)
        vm.lhoff = min(getattr(ps, 'lhoff', 0), lhmax)
        vm.settle(ltop=ltop, reveal=None, lhmax=lhmax, lhoff=vm.lhoff)

    def _detail_vm(self, vm, ps, ctx, prof, cur, dih, diw):
        '''The detail box: the browsed profile's authored definition (left pane focused), else the
        highlighted component's description, availability, needs, attrs, dependents and profiles.'''
        if vm.desc_h <= 0:
            vm.detail_title = None
            return
        lines = vm.detail_lines
        defs = ctx.config.profile_layer_defs(prof) if (ps.focus == 'left' and prof) else []
        if defs:                                         # the profile's RAW .hu definition, top layer
            top_def = defs[-1]
            vm.detail_title = f'profile: {prof}  [{top_def["role"]}]'
            shown = [f'"{t}"' if str(t).startswith('^') else str(t) for t in top_def['terms']]
            body = '[ ' + '  '.join(shown) + ' ]' if shown else '[ ]'
            lines.extend((k, line, 'info') for k, line in enumerate(_wordwrap(body, diw)[:dih - 1]))
            if len(defs) > 1:                            # name the lower layers that also define it
                lines.append((dih - 1, '(also in: ' + ', '.join(d['role'] for d in defs[:-1]) + ')',
                              'method_dim'))
            return
        vm.detail_title = cur or 'component'
        if not cur:
            return
        comp = ctx.routes.components.get(cur)
        desc = (comp.description if comp else '') or '(no description yet)'
        unavail = vm.cur_oses is not None
        rows = (dih - 5) if unavail else (dih - 4)
        lines.extend((k, line, 'info') for k, line in enumerate(_wrap(desc, diw)[:max(0, rows)]))
        if unavail:
            block = ctx.os_info.block
            lines.append((dih - 5, f'⊘ no install method on {block} · available on: {", ".join(vm.cur_oses)}'
                          if vm.cur_oses else f'⊘ no install method on {block} (declines on every '
                          'modeled OS)', 'issue_warning'))
        parts_here = ps._parts(cur)
        if parts_here:
            label, deps = 'parts', parts_here
        else:
            label, deps = 'requires', [str(d) for d in (getattr(comp, 'requires', None) or [])]

        def annot(d):
            if d in ctx.routes.components:
                _av, via, pin = ps._resolve(d)
                return f'{d}[{"*" if pin else ""}{via or "—"}]'
            return d                                     # a capability, not an installable component
        lines.append((dih - 4, (f'{label}: ' + '  '.join(annot(d) for d in deps)) if deps
                      else f'{label}: (none)', 'dependents'))
        atags = getattr(comp, 'attrs', []) if comp else []
        lines.append((dih - 3, ('attrs: ' + ' '.join(
            ('✓' if a.lower() in ps.attr_inc else '✗' if a.lower() in ps.attr_exc else '') + a
            for a in atags)) if atags else 'attrs: (untagged)', 'method_dim'))
        try:
            dependents = ctx.routes.dependents(cur)
        except Exception:                                # noqa: BLE001 — never let the detail box break the screen
            dependents = []
        lines.append((dih - 2, ('required by: ' + ', '.join(f'⎈ {n}' if is_drv else n
                                                             for n, is_drv in dependents))
                      if dependents else 'required by: (none)', 'dependents'))
        try:
            direct, indirect = ctx.config.profiles_containing(cur)
        except Exception:                                # noqa: BLE001 — never let the detail box break the screen
            direct, indirect = [], []
        lines.append((dih - 1, ('in profiles: ' + ' '.join(['● ' + p for p in direct]
                                                          + ['↳ ' + p for p in indirect]))
                      if (direct or indirect) else 'in profiles: (none)', 'method_dim'))

    def _catalog_vm(self, vm, ps, ctx, crows, rih, riw):
        '''The catalog matrix: its column spec (header) and the visible window of rows, each a list
        of positioned cells.'''
        disp = ctx.config.dispositions()                 # {comp: seen|interesting} for the markers
        _ov_inst, ov_orph, _ov_uninst = vm.overlay
        machines = ps.machines_list()
        tgset = ps.targets()
        picks_map = ctx.config.picks()
        uq = ctx.config.uninstall_queue()                # staged-for-uninstall -> ⮾ in the inst'd column
        tracked_here = ctx.config.included()             # tracked on THIS box -> ● vs ⊙ (installed-untracked)
        # an IGNORED orphan (orphans-ignore: — `.` toggles it) is dimmed: the user said "leave it be".
        # The overlay's async orphan classification carries `ignored` (glob over comp OR package key);
        # the config globs over the name cover the frames before that scan lands (and right after `.`).
        try:
            ign_globs = list(ctx.config.orphans_ignore() or ())
        except Exception:                                # noqa: BLE001 — never break the paint
            ign_globs = []

        def ignored_orphan(nm):
            o = ov_orph.get(nm) if isinstance(ov_orph, dict) else None
            return bool(getattr(o, 'ignored', False)) or any(fnmatchcase(nm, g) for g in ign_globs)

        n = len(crows)
        body_rows = max(1, rih - 1)                       # one row reserved for the column header
        rcur = max(0, min(ps.rcur, n - 1))
        rtop = _scroll_top(rcur, ps.rtop, body_rows, n)
        STATE = [("inst'd", 7), ('new', 4), ('flag', 5)]   # tracked is the per-machine cells, not a col
        state_w = sum(cw for _hd, cw in STATE)
        via_w, org_w = 10, 14                             # `from` (origin) roomier — plugin names are long
        MGAP = 3
        mach_w = [max(6, min(14, len(m))) + MGAP for m in machines]
        fixed = 2 + (via_w + 1) + (org_w + 1) + (1 + state_w) + 1     # all but name + machines
        x_name = 2
        name_w = max(16, min(30, riw - fixed - sum(mach_w)))
        x_via = x_name + name_w + 1
        x_org = x_via + via_w + 1
        x_state = x_org + org_w + 1
        st_x = [x_state + sum(cw for _hd, cw in STATE[:j]) for j in range(len(STATE))]
        x_mach0 = x_state + state_w + 1
        m_base = [x_mach0 + sum(mach_w[:k]) for k in range(len(machines))]
        vm.cat_w = x_mach0 + sum(mach_w)
        vm.rcol_left = max(0, min(getattr(ps, 'rcol_left', 0), max(0, vm.cat_w - riw)))
        vm.cat_n, vm.rtop = n, rtop
        # the key handler clamps ←/→ against rhmax; _probe_dirty is consumed (this frame reflects
        # any folded-in probes)
        vm.settle(rcur=rcur, rtop=rtop, rcol_left=vm.rcol_left, rhmax=max(0, vm.cat_w - riw),
                  _probe_dirty=False)

        vm.cat_header = ([(x_name, _fit('COMPONENT', name_w), 'menu_header', False),
                          (x_via, _fit('via', via_w), 'menu_header', False),
                          (x_org, _fit('from', org_w), 'menu_header', False)]
                         + [(sx, _fit(word, cw), 'menu_header', False) for (word, cw), sx in zip(STATE, st_x)]
                         + [(m_base[mi], _fit(m, mach_w[mi] - MGAP), 'link' if m in tgset else 'method_dim',
                             m in tgset) for mi, m in enumerate(machines)])
        for i in range(rtop, min(n, rtop + body_rows)):
            name, depth = crows[i]
            vm.shown.append(name)
            vm.shown.extend(ps._parts(name))             # probe a parts-aggregator's members too
            avail, via, pinned = ps._resolve(name)
            istate = ps.install_state(name)              # 'all' · 'some' (parts partial) · 'none'
            d = disp.get(name)
            is_new = ctx.config.is_new(name)
            nelem = ('info_dim' if not avail else 'link' if d == 'interesting'
                     else 'menu_new' if is_new else 'info_dim' if d == 'seen' else 'component')
            if depth:
                prefix = '  ↳ '
            elif ps.is_expandable(name):
                prefix = '▾ ' if name in ps.expanded_parts else '▸ '
            else:
                prefix = '  '                            # align leaves with the twisty column
            pw = len(prefix)
            via_txt = (f'[{via}]' if pinned else via) if via else ('—' if not avail else '')
            # inst'd: ⮾ staged-for-uninstall · ● installed+tracked · ⊙ installed+untracked (dimmed
            # when ignored) · ◐ partial · ⊘ no method on this OS · ○ none
            if name in uq:
                inst = ('⮾', 'orphan_lurking')
            elif istate == 'all':
                inst = ('●' if name in tracked_here else '⊙',
                        'installed' if name in tracked_here
                        else 'info_dim' if ignored_orphan(name) else 'orphan_lurking')
            elif istate == 'some':
                inst = ('◐', 'installed')
            elif not avail:
                inst = ('⊘', 'info_dim')
            else:
                inst = ('○', 'info_dim')
            cells = [(0, '#' if name in ps.selected_comps else ' ', 'component', None),
                     (x_name, prefix, nelem, None),
                     (x_name + pw, _fit(name, max(0, name_w - pw)), nelem,
                      'underline' if istate == 'all' else None),
                     (x_via, _fit(via_txt, via_w), 'method_dim', None),
                     (x_org, _fit(ps.origin(name), org_w), 'method_dim', None)]
            for (glyph, role), sx in zip([inst, ('◆' if is_new else ' ', 'menu_new'),
                                          ('☆' if d == 'interesting' else '·' if d == 'seen' else ' ',
                                           'link' if d == 'interesting' else 'info_dim')], st_x):
                cells.append((sx, glyph, role, None))
            for mi, m in enumerate(machines):            # per-machine tracked cells, centered
                picked = name in picks_map.get(m, ())
                gx = m_base[mi] + max(0, (mach_w[mi] - MGAP - 1)) // 2
                cells.append((gx, '●' if picked else '○', 'installed' if picked else 'info_dim',
                              'bold' if (picked and m in tgset) else None))
            vm.cat_rows.append(CatRow(cells, i == rcur))

    # -- draw -------------------------------------------------------------

    def draw(self, stdscr, pal, vm):
        h, w = self.begin_page(stdscr, pal)
        top, body_h, lw = vm.top, vm.body_h, vm.lw
        rleft, rw = lw + 1, w - lw - 1
        _sel = pal.sel_bg_rgb
        residual_bg = tuple(round(_sel[i] * 0.55) for i in range(3))   # dimmer bar: unfocused current row
        low_color = not pal.have256    # 8/16-colour has no room for a dim tint -> reverse-video instead
        rbg_of = lambda unfocused_cur: (None if low_color else residual_bg) if unfocused_cur else None

        # LEFT: the profile tree
        lit, lil, lih, liw = _panel(stdscr, pal, top, 0, body_h, lw, vm.ltitle, vm.focus == 'left', h, w)
        lho = vm.lhoff
        for vis, row in enumerate(vm.left_rows):
            y = lit + vis
            foc = row.cur and vm.focus == 'left'
            unfoc = row.cur and not foc
            rbg = rbg_of(unfoc)
            rev = curses.A_REVERSE if (low_color and unfoc) else 0
            if foc:
                _put(stdscr, y, lil, ' ' * liw, pal.fill(y, lil, h, w, selected=True))
            elif unfoc:
                _put(stdscr, y, lil, ' ' * liw,
                     curses.A_REVERSE if low_color else pal.fill(y, lil, h, w, bg=residual_bg))
            _put(stdscr, y, lil, _fit(row.text[lho:], liw),
                 pal.style('profile', y, lil, h, w, selected=foc, bg=rbg)
                 | rev | (curses.A_DIM if row.struck and not foc else 0))
            if not foc:                                  # the count badges in their own hues
                for text, hue in row.badges:
                    vx = row.text.rindex(text) - lho
                    if 0 <= vx and vx + len(text) <= liw:
                        _put(stdscr, y, lil + vx, text, pal.style(hue, y, lil + vx, h, w, bg=rbg) | rev)
        _scrollbar_v(stdscr, pal, lit, lw - 1, lih, vm.ltop, lih, vm.left_n, h, w)
        if vm.left_max > liw:                            # horizontal thumb on the pane's bottom border
            _scrollbar_h(stdscr, pal, top + body_h - 1, lil, liw, lho, liw, vm.left_max, h, w)

        # RIGHT TOP: the detail box
        if vm.detail_title is not None:
            dit, dil, _dih, diw = _panel(stdscr, pal, top, rleft, vm.desc_h, rw, vm.detail_title,
                                         False, h, w)
            for row, text, role in vm.detail_lines:
                _put(stdscr, dit + row, dil, _fit(text, diw), pal.style(role, dit + row, dil, h, w))

        # RIGHT BOTTOM: the catalog matrix
        ctop, cath = top + vm.desc_h, body_h - vm.desc_h
        rit, ril, rih, riw = _panel(stdscr, pal, ctop, rleft, cath, rw, vm.ctitle, vm.focus == 'right', h, w)
        rhoff = vm.rcol_left

        def hput(y, xoff, text, attr):                   # draw at xoff-rhoff, clipping both edges
            ax = xoff - rhoff
            if ax >= riw:
                return
            if ax < 0:
                text, ax = text[-ax:], 0
            if text:
                _put(stdscr, y, ril + ax, _fit(text, riw - ax), attr)

        for x, text, role, bold in vm.cat_header:
            hput(rit, x, text, pal.style(role, rit, ril, h, w) | (curses.A_BOLD if bold else 0))
        flag_attr = {'underline': curses.A_UNDERLINE, 'bold': curses.A_BOLD, None: 0}
        for r, row in enumerate(vm.cat_rows):
            y = rit + 1 + r
            foc = row.cur and vm.focus == 'right'
            rev = curses.A_REVERSE if (low_color and row.cur and not foc) else 0
            if foc:
                _put(stdscr, y, ril, ' ' * riw, pal.fill(y, ril, h, w, selected=True))
            elif rev:
                _put(stdscr, y, ril, ' ' * riw, curses.A_REVERSE)
            for x, text, role, flag in row.cells:
                hput(y, x, text, pal.style(role, y, ril + x, h, w, selected=foc) | rev | flag_attr[flag])
        body_rows = max(1, rih - 1)
        _scrollbar_v(stdscr, pal, rit + 1, rleft + rw - 1, body_rows, vm.rtop, body_rows, vm.cat_n, h, w)
        if vm.cat_w > riw:                               # horizontal thumb on the bottom border
            _scrollbar_h(stdscr, pal, ctop + cath - 1, ril, riw, rhoff, riw, vm.cat_w, h, w)

        status = vm.status + (f'    {vm.note}' if vm.note else '')
        _sty = lambda row, x: pal.style('status_line', row, x, h, w)
        lg1_x = max(0, w - len(vm.legend1))
        lg2_x = max(0, w - len(vm.legend2))
        _put(stdscr, h - 4, 0, _fit(status, max(1, lg1_x - 1)), _sty(h - 4, 0))
        _put(stdscr, h - 4, lg1_x, _fit(vm.legend1, w - lg1_x), _sty(h - 4, lg1_x))
        _put(stdscr, h - 3, lg2_x, _fit(vm.legend2, w - lg2_x), _sty(h - 3, lg2_x))
        self.end_page(stdscr, pal, None, [vm.nav1, vm.nav2], h, w)

    def commit(self, vm):
        super().commit(vm)
        if self.model.show_install and getattr(vm, 'shown', None):
            self.model.ensure_probes(vm.shown)          # probe the just-drawn rows, after the paint

    # -- handle -----------------------------------------------------------

    def _redraw(self, stdscr, pal, note):
        '''The modal redraw callback (filter/find edits) — re-render THIS screen so the modal paints
        over a current frame (no dependency on the legacy painter).'''
        self.render(stdscr, pal, self.model.ctx, note)

    def handle(self, ch, ctx, stdscr, pal):
        '''One key. Mutates the model, runs the modals, returns an Intent(note, dirty, pending_notes,
        open_where). Ported verbatim from the former profiles dispatch; the `machine-target` branch
        rebuilds the model (as the loop used to rebind `ps`) and swaps it in as self.model.'''
        from ... import actions
        ps = self.model
        km = menu._keymap()
        pfact = km.action_for('profiles', ch)
        note = None
        dirty = False
        pending = []
        open_where = None
        wrote = []                                 # a config write was attempted (for the --pretend note)

        def _w(fn):
            wrote.append(True)
            return fn
        if pfact in menu._NAV_ACTIONS:
            if ps.focus == 'left':
                ps.lcur = menu.ListNav.apply(pfact, ps.lcur, len(ps.visible_pnodes()) - 1,
                                             lambda: _page_rows(stdscr))
            else:                              # the catalog: down = the next item
                ps.rcur = menu.ListNav.apply(pfact, ps.rcur, len(ps.vcatalog()) - 1,
                                             lambda: _page_rows(stdscr))
        elif pfact in ('switch-pane', 'switch-pane-back'):
            ps.focus = 'right' if ps.focus == 'left' else 'left'   # tab / shift-tab toggle
        elif pfact == 'confirm' and ps.focus == 'left':
            _nd = ps.cur_node()
            if _nd and _nd[3]:               # expandable -> drill the tree in place (reveal subs)
                (ps.collapse_cur if _nd[4] else ps.expand_cur)()
            else:
                ps.focus = 'right'             # a leaf profile: open the components pane for it
        elif pfact == 'right':
            if ps.focus == 'left':
                if ps.cur_node() and ps.cur_node()[3]:   # expandable -> open the include tree
                    ps.expand_cur()
                else:                          # else scroll the (overflowing) left pane right
                    ps.lhoff = min(getattr(ps, 'lhmax', 0), getattr(ps, 'lhoff', 0) + 4)
            else:
                _vc = ps.vcatalog()            # a collapsed parts comp -> drill it open (twisty)
                _nm = _vc[ps.rcur] if 0 <= ps.rcur < len(_vc) else None
                if _nm and ps.is_expandable(_nm) and _nm not in ps.expanded_parts:
                    ps.expanded_parts.add(_nm)
                else:                          # else scroll the matrix table right
                    ps.rcol_left = min(getattr(ps, 'rhmax', 0), ps.rcol_left + 6)
        elif pfact == 'left':
            if ps.focus == 'left':
                if getattr(ps, 'lhoff', 0) > 0:   # scroll back first, then collapse/parent
                    ps.lhoff = max(0, ps.lhoff - 4)
                else:
                    ps.collapse_cur()
            else:
                _vc = ps.vcatalog()            # an expanded parts comp -> collapse the twisty
                _nm = _vc[ps.rcur] if 0 <= ps.rcur < len(_vc) else None
                if _nm and _nm in ps.expanded_parts:
                    ps.expanded_parts.discard(_nm)
                elif ps.rcol_left > 0:
                    ps.rcol_left = max(0, ps.rcol_left - 6)   # scroll the matrix table left
                else:
                    ps.focus = 'left'          # at the left edge -> back to the browse pane
        elif pfact == 'toggle-install':
            ps.show_install = 0 if ps.show_install else 1   # off <-> on (installed underlined,
            # installed-but-unpicked ⊙ coloured, ignored orphans dimmed). NOTE: don't invalidate the
            # overlay cache here — the data is identical on/off (only the rendering differs).
            note = ('install overlay off',
                    'install overlay ON — installed underlined, installed-but-unpicked ⊙ '
                    'coloured, ignored orphans dimmed')[ps.show_install]
        elif pfact == 'stage-uninstall' and ps.focus == 'right':
            _targets = ps.action_targets()         # stage the set (else the cursor) for uninstall
            if _targets:                           # (idempotent — like Components `x`; unstage there)
                nch = 0
                try:
                    for _c in _targets:
                        if _c in ctx.config.uninstall_queue():
                            continue
                        changed, _lbl = _w(actions.stage_uninstall)(ctx, _c, on=True)
                        nch += 1 if changed else 0
                    ps.selected_comps.clear()
                    ps.reload(); dirty = dirty or nch > 0
                    note = (f'{nch} staged for uninstall (!uninstall)' if nch
                            else 'no change (already staged?)')
                except ConfigsysError as e:
                    note = f'stage-uninstall failed: {e}'
        elif pfact in ('disp-interesting', 'disp-seen', 'disp-interesting-all', 'disp-seen-all'):
            _batch = pfact.endswith('-all')        # S/I: the set / whole profile · s/i: the cursor
            _targets = ps.action_targets() if _batch else ps.cursor_targets()
            if _targets:                           # cursor: toggle (press again -> NEW); batch: set
                _want = 'interesting' if 'interesting' in pfact else 'seen'
                _single = len(_targets) == 1 and not _batch
                nch = 0
                try:
                    for _c in _targets:
                        # SEEN must not clobber INTERESTING (the flag is the stronger state)
                        if _want == 'seen' and ctx.config.disposition(_c) == 'interesting':
                            continue
                        _state = ('new' if (_single and ctx.config.disposition(_c) == _want)
                                  else _want)
                        changed, _lbl = _w(actions.set_disposition)(ctx, _c, _state)
                        nch += 1 if changed else 0
                    if _batch:
                        ps.selected_comps.clear()
                    ps.reload(); dirty = dirty or nch > 0
                    note = (f'{nch} -> {_want.upper()}' if not _single
                            else f'{_targets[0]}: '
                                 f'{"NEW" if ctx.config.disposition(_targets[0]) is None else _want.upper()}')
                except ConfigsysError as e:
                    note = f'disposition failed: {e}'
        elif pfact in ('track-all', 'track-one'):
            # T = the multi-select set / whole selected profile; t = just the highlighted item.
            _targets = ps.action_targets() if pfact == 'track-all' else ps.cursor_targets()
            if _targets:
                tg = sorted(ps.targets())          # the selected target machines (fan-out)
                # toggle: if ALL targets are already fully tracked here, UNtrack; else track.
                on = not all(ps.target_state(c) == 'all' for c in _targets)
                nch = 0
                try:
                    for _c in _targets:
                        cn, _l = _w(actions.set_included)(ctx, _c, tg, on)
                        nch += cn
                    if on:                         # tracked implies seen (undispositioned -> seen)
                        _w(actions.mark_all_seen)(ctx, _targets)
                    if pfact == 'track-all':
                        ps.selected_comps.clear()
                    ps.reload(); dirty = dirty or nch > 0
                    _lbl = _targets[0] if len(_targets) == 1 else f'{len(_targets)} components'
                    note = (f'{_lbl} {"tracked on" if on else "untracked from"} {", ".join(tg)}'
                            if nch else 'no change')
                except ConfigsysError as e:
                    note = f'{pfact} failed: {e}'
        elif pfact == 'orphan-ignore' and ps.focus == 'right':
            _vc = ps.vcatalog()                    # toggle the selected orphan's ignore state
            if _vc:
                _c = _vc[ps.rcur]
                try:
                    if _c in ctx.config.orphans_ignore():
                        changed, lbl = actions.unignore_orphan(ctx, _c)
                        note = f'{_c} un-ignored' if changed else f'{_c}: {lbl}'
                    else:
                        changed, lbl = actions.ignore_orphan(ctx, _c)
                        note = f'{_c} added to orphans-ignore' if changed else f'{_c}: {lbl}'
                    ps.reload()
                except ConfigsysError as e:
                    note = f'ignore failed: {e}'
        elif pfact == 'mark-all-seen':         # `E`: acknowledge every NEW component at once
            _new = [c for c in ps.catalog if ctx.config.is_new(c) and not ps._is_companion(c)]
            if not _new:
                note = 'nothing NEW to mark seen'
            elif _popup_choose(stdscr, pal, f'mark all {len(_new)} NEW components as seen?',
                               [('cancel', ''), ('mark seen', '')], 0) == 1:
                nch = _w(actions.mark_all_seen)(ctx, _new)
                ps.reload()
                note = f'{nch} marked seen'
        elif pfact == 'claim':                 # `C`: track everything already INSTALLED (adopt a box)
            _busy(stdscr, pal, 'scanning installed…')   # a full scan; give feedback before the freeze
            _claim = ps.installed_scan()       # full catalog: batch indices + per-component get_version
            tg = sorted(ps.targets())
            if not _claim:
                note = 'nothing installed to claim'
            elif _popup_choose(stdscr, pal,
                               f'track {len(_claim)} installed components on {", ".join(tg)}?',
                               [('cancel', ''), ('claim', '')], 0) == 1:
                nch = 0
                for _cc in _claim:
                    for _m in tg:
                        cn, _l = _w(actions.set_included)(ctx, _cc, [_m], True)
                        nch += cn
                _w(actions.mark_all_seen)(ctx, _claim)   # tracked implies seen
                ps.reload(); dirty = True
                note = f'claimed {len(_claim)} installed → tracked on {", ".join(tg)}'
        elif pfact == 'filter':                # FILTER the focused pane (live; narrows)
            if ps.focus == 'left':
                _filter_edit(stdscr, ps.pfilter, ps.set_pfilter,
                             lambda: self._redraw(stdscr, pal, note))
            else:
                _filter_edit(stdscr, ps.cfilter, ps.set_cfilter,
                             lambda: self._redraw(stdscr, pal, note))
        elif pfact == 'attr-filter':           # faceted attr filter over the catalog (kind)
            res = _attr_filter_modal(stdscr, pal, ps.attr_inc, ps.attr_exc)
            if res is not None:
                ps.attr_inc, ps.attr_exc = res
                ps.rcur, ps.rcol_left = 0, 0   # catalog membership changed -> reset its cursor
        elif pfact == 'find':                  # fuzzy FIND in the focused pane: jump cursor
            rdraw = lambda: self._redraw(stdscr, pal, note)
            if ps.focus == 'left':
                _find_edit(stdscr, [nd[0] for nd in ps.visible_pnodes()], ps.lcur,
                           lambda i: setattr(ps, 'lcur', i), rdraw)
            else:
                _find_edit(stdscr, list(ps.vcatalog()), ps.rcur,
                           lambda i: setattr(ps, 'rcur', i), rdraw)
        elif pfact == 'select-all':
            # `a`: (de)select every component in view — the browsed profile's members when the
            # left pane is focused, else the catalog rows currently shown.
            if ps.focus == 'left':
                prof = ps.cur_curate()
                allvis = ps.members(prof) if prof else set()
            else:
                allvis = set(ps.vcatalog())
            if allvis:
                if allvis <= ps.selected_comps:
                    ps.selected_comps -= allvis
                else:
                    ps.selected_comps |= allvis
                note = (f'{len(ps.selected_comps)} selected' if ps.selected_comps
                        else 'selection cleared')
        elif pfact == 'method' and ps.focus == 'right':
            vcat = ps.vcatalog()
            if vcat:                               # pin the selected component's install method
                name = vcat[ps.rcur]
                changed, note, deferred = _pick_method_name(stdscr, pal, ctx, name)
                if deferred:
                    pending.append(deferred)
                if changed:
                    ctx.invalidate()               # re-read so the new [via] pin shows
                    ps._res.pop(name, None)        # its resolution changed -> drop the stale entry
                    ps._parts_cache.pop(name, None)   # its parts may change with the new method too
                    ps.reload()
                    dirty = True
        elif pfact == 'comp-machines' and ps.focus == 'right':
            vcat = ps.vcatalog()                   # toggle THIS component's tracking per machine
            if vcat:
                _c = vcat[ps.rcur]
                mnote = _w(_component_machines_modal)(stdscr, pal, ctx, _c)
                ps.reload(); dirty = True
                note = mnote or f'{_c} machines'
        elif pfact == 'machine-target':          # target machines + add/rename/remove (modal)
            before = set(ps.targets())
            cur, mnote = _machines_modal(stdscr, pal, ctx, before)
            # refresh IN PLACE (B16 / tui-screens-04): a rebuilt model dropped the expanded tree, the
            # attr filter, the overlay and the warm caches, so the cursor landed on another component
            ps.target_machines = cur
            ps.reload()                          # re-reads profiles/catalog/machines, clamps
            dirty = bool(mnote) or set(cur) != before
            note = mnote or f'targets: {", ".join(sorted(cur)) or "(none)"}'
        elif pfact == 'where':                     # full-page `where`: the cursor COMPONENT when the
            if ps.focus == 'right':                # table is focused (like Components), else the
                _vc = ps.vcatalog()                # current profile's provenance
                _wc = _vc[ps.rcur] if 0 <= ps.rcur < len(_vc) else None
                if _wc:
                    from ...cli.where import where_report
                    open_where = (where_report(ctx, _wc) or [f'{_wc}: nothing to show'], _wc)
            else:
                _wp = ps.cur_profile()
                if _wp:
                    from ...cli.where import where_profile_report
                    where_lines = where_profile_report(ctx, _wp) or [f'{_wp}: nothing to show']
                    open_where = (where_lines, _wp)
        elif pfact == 'select' and ps.focus == 'right':
            vcat = ps.vcatalog()               # `space`: build the multi-select set (A/I/S/X batch)
            if vcat:
                nm = vcat[ps.rcur]
                ps.selected_comps ^= {nm}
                note = (f'{len(ps.selected_comps)} selected' if ps.selected_comps
                        else 'selection cleared')
        elif pfact == 'confirm' and ps.focus == 'right':
            vcat = ps.vcatalog()               # `enter`: drill a parts comp open/closed, else
            if vcat:                           #         toggle Included for the cursor on targets
                name = vcat[ps.rcur]
                if ps.is_expandable(name):     # a `via: parts` aggregator -> reveal/hide its pieces
                    ps.toggle_expand_part(name)
                else:
                    tg = sorted(ps.targets())
                    on = ps.target_state(name) != 'all'   # not fully on -> include; else exclude
                    try:
                        nch, _l = _w(actions.set_included)(ctx, name, tg, on)
                        if on:                            # tracked implies seen
                            _w(actions.mark_all_seen)(ctx, [name])
                        ps.reload()
                        dirty = dirty or nch > 0
                        note = (f'{name} {"included on" if on else "excluded from"} {", ".join(tg)}'
                                if nch else 'no change')
                    except ConfigsysError as e:
                        note = f'edit failed: {e}'
        if wrote and getattr(ctx.runner, 'pretend', False):   # --pretend: the writers refused; the
            note = menu._pretend_note(ctx, None, True)         # counts/notes above would misreport it
        return Intent(note=note, dirty=dirty, pending_notes=pending or None, open_where=open_where)
