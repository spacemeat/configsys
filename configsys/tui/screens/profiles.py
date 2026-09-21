'''profiles.py — the Profiles browse/matrix screen as a Screen (build_vm/draw/handle).

Migrated off the monolithic menu.py painter (docs/d2-mvvm-plan.md), after the Plugins / Config /
Dotfiles / Glue pattern-setters. The model is the existing `menu.ProfileScreen` (profile tree +
component catalog + matrix state, the overlay/probe machinery), composed unchanged; this adds the
three MVVM seams:

- build_vm: the PURE chrome content — the selected profile, the two panel titles, the status line
  (sans the transient note), the two legend rows and the two nav rows. This screen's body reads
  deeply from the model (per-row resolution, per-cell picks, badge counts), so the first pass keeps
  the VM deliberately light and lets `draw` read the model for the heavy content — the primary win
  here is the own-file Screen interface and a `handle` extracted from `run()`.
- draw: reproduces menu._draw_profiles cell for cell (test_screen_profiles pins it against the
  legacy painter). It reads `self.model.ctx` wherever the legacy painter read its `ctx` parameter,
  so a sample overlay ctx (menu._sample_profiles_state) is honoured identically.
- handle: the former `if screen == 'profiles'` dispatch, returning an Intent (note / dirty /
  pending_notes / open_where) instead of mutating loop-scope locals. The `machine-target` branch,
  which REBOUND the loop's `ps`, rebinds `self.model` internally.
'''

import curses

from .. import menu
from ..menu import (_GKEY, ProfileScreen as _ProfilesModel, _attr_filter_modal, _busy,
                    _component_machines_modal, _draw_nav, _fill_bg, _filter_edit, _find_edit, _fit,
                    _machines_modal, _page_rows, _panel, _pick_method_name, _popup_choose, _put,
                    _scroll_reveal, _scroll_top, _scrollbar_h, _scrollbar_v, _wordwrap, _wrap)
from ...errors import ConfigsysError
from .base import Intent, Screen, ViewModel


class ProfilesVM(ViewModel):
    '''Pure chrome content for one Profiles frame — settled by build_vm, painted by draw. (The
    catalog/table body is painted straight from the model this pass; see the module docstring.)'''

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


def _nav_strs():
    km = menu._KEYMAP
    if km is not None:
        g = lambda a: km.glyph('profiles', a)
        nav1 = (f" {g('down')}/{g('up')} move · {g('right')}/{g('left')} scroll/expand · "
                f"{g('switch-pane')} panes · {g('find')} find · {g('filter')} filter · "
                f"{g('attr-filter')} attrs · {g('machine-target')} machines ")
        nav2 = (f" {g('track-all')} track-set · {g('track-one')} track-one · {g('disp-interesting')} int · "
                f"{g('disp-seen')} seen · {g('select')} sel · {g('select-all')} all · "
                f"{g('method')} via · {g('stage-uninstall')} uninst · {g('quit')} quit ")
    else:
        nav1 = (' j/k move · h/l scroll/expand · tab panes · / find · F filter · f attrs · M machines ')
        nav2 = (' T track-set · t track-one · i int · s seen · space sel · a all · v via · x uninst · q quit ')
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
        return vm

    # -- draw -------------------------------------------------------------

    def draw(self, stdscr, pal, vm):
        ps = self.model
        ctx = ps.ctx                                     # where the legacy painter read its ctx param
        screen = 'profiles'
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        pal.use_page(screen)
        if pal.gradient:
            _fill_bg(stdscr, pal, h, w)
        _draw_nav(stdscr, pal, screen, h, w)

        top, body_h = 1, max(1, h - 5)                   # TWO status/legend rows, then TWO nav rows below
        lw = max(16, w // 6) + 6                          # profiles pane: narrow, leaving the grid room (+6 cols)
        rleft, rw = lw + 1, w - lw - 1
        prof = vm.prof                                   # the selected profile
        _ceil = ps.cur_ceiling()                          # per-layer read: a system row shows pristine members
        # the legacy painter computed these (unused in the paint) — kept as calls so the model's
        # per-frame caches warm identically
        ps.members(prof, _ceil)
        ps.own_members(prof, _ceil)
        ps.removed_members(prof, _ceil)
        _disp = ctx.config.dispositions()                # {comp: seen|interesting} for the catalog markers
        ov_inst, ov_orph, ov_uninst = ps.overlay()       # install-axis overlay data (empty unless `O` on)
        _sel = pal.sel_bg_rgb
        residual_bg = tuple(round(_sel[i] * 0.55) for i in range(3))   # dimmer bar: unfocused current row
        low_color = not pal.have256    # 8/16-colour has no room for a dim tint -> reverse-video instead

        # LEFT: profiles as a tree — top-level + inline `+include` children
        vnodes = ps.visible_pnodes()
        lit, lil, lih, liw = _panel(stdscr, pal, top, 0, body_h, lw, vm.ltitle,
                                    ps.focus == 'left', h, w)
        if ps.reveal is not None:                        # a just-expanded node -> reveal its subtree
            pi = next((i for i, nd in enumerate(vnodes) if nd[2] == ps.reveal), None)
            if pi is not None:
                pd, end = vnodes[pi][1], pi
                for j in range(pi + 1, len(vnodes)):
                    if vnodes[j][1] > pd:
                        end = j
                    else:
                        break
                ps.ltop = _scroll_reveal(pi, end, ps.ltop, lih, len(vnodes))
            ps.reveal = None
        ps.ltop = _scroll_top(ps.lcur, ps.ltop, lih, len(vnodes))
        _lho = getattr(ps, 'lhoff', 0)                   # browse-pane horizontal char offset
        _lmax = 0                                        # widest visible row -> sets ps.lhmax below
        group_counts = {}                                # per-group root count for the header badges
        if ps.grouped:
            _pf = ps.pfilter.lower()
            for _p in (ps.profiles if not _pf else [x for x in ps.profiles if _pf in x.lower()]):
                for g in ps._profile_groups(_p):         # a profile counts under every group it defines in
                    group_counts[g] = group_counts.get(g, 0) + 1
        for vis, i in enumerate(range(ps.ltop, min(len(vnodes), ps.ltop + lih))):
            name, depth, key, expandable, expanded, kind = vnodes[i][:6]
            node_group = vnodes[i][6] if len(vnodes[i]) > 6 else None
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
            if kind == 'group':                           # a layer-group header row
                gid = key[len(_GKEY):]
                _gnew, _gint = ps.group_new_count(gid)
                hdr = (f'{"▾" if expanded else "▹"} {name} ({group_counts.get(gid, 0)})'
                       + (f'  ⁺{_gnew}' if _gnew else '') + (f'  ☆ {_gint}' if _gint else ''))
                _lmax = max(_lmax, len(hdr))
                _put(stdscr, y, lil, _fit(hdr.upper()[_lho:], liw),
                     pal.style('menu_header', y, lil, h, w, selected=foc, bg=(None if low_color else rbg))
                     | rev)
                continue
            exp = '▾' if expanded else ('▹' if expandable else ' ')
            scope = '▸' if i == ps.lcur else ' '         # marks the profile the catalog is showing
            prefix = list(f'{scope}{"  " * depth}{exp}')
            # Exclusion attribution: paint a `~` in the at-fault ancestor's status-glyph column.
            struck = False
            _parts = key.split('\x00')
            if node_group:                                        # a grouped key is group-prefixed
                _parts = _parts[1:]
            for ai, anc in enumerate(_parts[:-1]):                # ancestors; path index == their depth
                try:
                    if name in ctx.config.profile_excludes(anc):
                        col = 2 + 2 * ai
                        if 0 <= col < len(prefix):
                            prefix[col] = '~'
                        struck = True
                except Exception:                                  # noqa: BLE001 — a bad profile marks nothing
                    pass
            _ceil_r = ps.group_ceiling(node_group)
            nnew = ps.profile_new_count(name, _ceil_r)
            nint = ps.profile_interesting_count(name, _ceil_r)
            nunt = ps.profile_untracked_count(name, _ceil_r)   # installed here but not tracked (claimable)
            newtag = f'  ⁺{nnew}' if nnew else ''
            inttag = f'  ☆ {nint}' if nint else ''
            unttag = f'  ⊙ {nunt}' if nunt else ''
            tag = newtag + inttag + unttag
            disp = f'+{name}' if kind == 'include' else name  # `+`-mark a live include child
            row = f'{"".join(prefix)} {disp}{tag}'
            _lmax = max(_lmax, len(row))
            _put(stdscr, y, lil, _fit(row[_lho:], liw),
                 pal.style('profile', y, lil, h, w, selected=foc, bg=(None if low_color else rbg))
                 | rev | (curses.A_DIM if struck and not foc else 0))
            # tint the count badges in their own hues (⁺N new · ☆N interesting · ⊙N installed-untracked)
            if not foc:
                for _bstr, _hue in ((f'⁺{nnew}' if nnew else '', 'menu_new'),
                                    (f'☆ {nint}' if nint else '', 'link'),
                                    (f'⊙ {nunt}' if nunt else '', 'installed')):
                    if _bstr:
                        vx = row.rindex(_bstr) - _lho
                        if 0 <= vx and vx + len(_bstr) <= liw:
                            _put(stdscr, y, lil + vx, _bstr,
                                 pal.style(_hue, y, lil + vx, h, w, bg=(None if low_color else rbg)) | rev)
        ps.lhmax = max(0, _lmax - liw)                   # clamp target for ←/→ (nav reads this next frame)
        ps.lhoff = min(_lho, ps.lhmax)
        _scrollbar_v(stdscr, pal, lit, lw - 1, lih, ps.ltop, lih, len(vnodes), h, w)
        if ps.lhmax:                                     # horizontal thumb on the browse pane's bottom border
            _scrollbar_h(stdscr, pal, top + body_h - 1, lil, liw, ps.lhoff, liw, _lmax, h, w)

        # RIGHT TOP: detail for the highlighted component — description + methods
        crows = ps._catalog_rows()                        # [(name, depth)] — parts children interleaved
        vcat = [nm for nm, _dep in crows]
        cur = vcat[ps.rcur] if vcat and 0 <= ps.rcur < len(vcat) else None
        desc_h = 8 if body_h >= 13 else 0    # one extra inner row for the parts/requires ("needs") line
        # When the PROFILE pane is focused on a profile, the detail box shows that profile's RAW .hu
        # DEFINITION — its top layer's authored term list; a note names lower layers.
        _defs = ctx.config.profile_layer_defs(prof) if (desc_h and ps.focus == 'left' and prof) else []
        if _defs:
            _grp = ps.cur_group()
            _rowdef = next((d for d in _defs if ps._fold_role(d['role']) == _grp), _defs[-1]) if _grp else _defs[-1]
            _ro = ' · browse-only' if ps.cur_readonly() else ''
            dit, dil, dih, diw = _panel(stdscr, pal, top, rleft, desc_h, rw,
                                        f'profile: {prof}  [{_rowdef["role"]}{_ro}]', False, h, w)
            top_def = _rowdef                                     # show THIS layer's authored terms
            shown = [f'"{t}"' if str(t).startswith('^') else str(t) for t in top_def['terms']]
            body = '[ ' + '  '.join(shown) + ' ]' if shown else '[ ]'
            for k, line in enumerate(_wordwrap(body, diw)[:dih - 1]):
                _put(stdscr, dit + k, dil, _fit(line, diw), pal.style('info', dit + k, dil, h, w))
            if len(_defs) > 1:                                    # name the lower layers that also define it
                _layer_note = '(also in: ' + ', '.join(d['role'] for d in _defs[:-1]) + ')'
                _put(stdscr, dit + dih - 1, dil, _fit(_layer_note, diw),
                     pal.style('method_dim', dit + dih - 1, dil, h, w))
        elif desc_h:
            dit, dil, dih, diw = _panel(stdscr, pal, top, rleft, desc_h, rw, cur or 'component', False, h, w)
            if cur:
                comp = ctx.routes.components.get(cur)
                desc = (comp.description if comp else '') or '(no description yet)'
                _unavail = not ps.available(cur)
                _desc_rows = (dih - 5) if _unavail else (dih - 4)
                for k, line in enumerate(_wrap(desc, diw)[:max(0, _desc_rows)]):
                    _put(stdscr, dit + k, dil, _fit(line, diw), pal.style('info', dit + k, dil, h, w))
                if _unavail:
                    _oses = ps.available_oses(cur)
                    _wtext = (f'⊘ no install method on {ctx.os_info.block} · available on: {", ".join(_oses)}'
                              if _oses else f'⊘ no install method on {ctx.os_info.block} (declines on every '
                              'modeled OS)')
                    _put(stdscr, dit + dih - 5, dil, _fit(_wtext, diw),
                         pal.style('issue_warning', dit + dih - 5, dil, h, w))
                _parts_here = ps._parts(cur)
                if _parts_here:
                    _nlabel, _deps = 'parts', _parts_here
                else:
                    _nlabel = 'requires'
                    _deps = [str(d) for d in (getattr(comp, 'requires', None) or [])]

                def _annot(d):
                    if d in ctx.routes.components:
                        _av, _via, _pin = ps._resolve(d)
                        return f'{d}[{"*" if _pin else ""}{_via or "—"}]'
                    return d                          # a capability, not an installable component
                _ntext = (f'{_nlabel}: ' + '  '.join(_annot(d) for d in _deps)) if _deps \
                    else f'{_nlabel}: (none)'
                _put(stdscr, dit + dih - 4, dil, _fit(_ntext, diw),
                     pal.style('dependents', dit + dih - 4, dil, h, w))
                atags = getattr(comp, 'attrs', []) if comp else []
                if atags:
                    shown = [(('✓' if a.lower() in ps.attr_inc else '✗' if a.lower() in ps.attr_exc else '')
                              + a) for a in atags]
                    atext = 'attrs: ' + ' '.join(shown)
                else:
                    atext = 'attrs: (untagged)'
                _put(stdscr, dit + dih - 3, dil, _fit(atext, diw),
                     pal.style('method_dim', dit + dih - 3, dil, h, w))
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

        # RIGHT BOTTOM: the component catalog as a single vertical TABLE (the v3 matrix)
        ctop, cath = top + desc_h, body_h - desc_h
        machines = ps.machines_list()
        tgset = ps.targets()
        picks_map = ctx.config.picks()
        _uq = ctx.config.uninstall_queue()               # staged-for-uninstall -> ⮾ in the inst'd column
        _cur_track = ctx.config.included()               # tracked on THIS box -> ● vs ⊙ (installed-untracked)
        rit, ril, rih, riw = _panel(stdscr, pal, ctop, rleft, cath, rw, vm.ctitle, ps.focus == 'right', h, w)
        n = len(vcat)
        body_rows = max(1, rih - 1)                       # one row reserved for the column header
        ps.rcur = min(ps.rcur, max(0, n - 1))
        ps.rtop = _scroll_top(ps.rcur, ps.rtop, body_rows, n)
        STATE = [("inst'd", 7), ('new', 4), ('flag', 5)]   # tracked is the per-machine cells, not a col
        state_w = sum(cw for _hd, cw in STATE)
        via_w, org_w = 10, 14                             # `from` (origin) roomier — plugin names are long
        MGAP = 3
        mach_w = [max(6, min(14, len(m))) + MGAP for m in machines]
        mach_block = sum(mach_w)
        fixed = 2 + (via_w + 1) + (org_w + 1) + (1 + state_w) + 1     # all but name + machines
        x_name = 2
        name_w = max(16, min(30, riw - fixed - mach_block))
        x_via = x_name + name_w + 1
        x_org = x_via + via_w + 1
        x_state = x_org + org_w + 1
        st_x = [x_state + sum(cw for _hd, cw in STATE[:j]) for j in range(len(STATE))]
        x_mach0 = x_state + state_w + 1
        m_base = [x_mach0 + sum(mach_w[:k]) for k in range(len(machines))]
        total_w = x_mach0 + mach_block
        ps.rcol_left = max(0, min(getattr(ps, 'rcol_left', 0), max(0, total_w - riw)))
        rhoff, hbar = ps.rcol_left, total_w > riw
        ps.rhmax = max(0, total_w - riw)                 # the key handler clamps ←/→ against this

        def _hput(y, xoff, text, attr):                 # draw at xoff-rhoff, clipping both edges
            ax = xoff - rhoff
            if ax >= riw:
                return
            if ax < 0:
                text = text[-ax:]
                ax = 0
            if text:
                _put(stdscr, y, ril + ax, _fit(text, riw - ax), attr)

        # header row
        hs = pal.style('menu_header', rit, ril, h, w)
        _hput(rit, x_name, _fit('COMPONENT', name_w), hs)
        _hput(rit, x_via, _fit('via', via_w), hs)
        _hput(rit, x_org, _fit('from', org_w), hs)
        for (word, cw), sx in zip(STATE, st_x):
            _hput(rit, sx, _fit(word, cw), hs)
        for mi, m in enumerate(machines):
            is_tg = m in tgset
            _hput(rit, m_base[mi], _fit(m, mach_w[mi] - MGAP),
                  pal.style('link' if is_tg else 'method_dim', rit, ril, h, w) | (curses.A_BOLD if is_tg else 0))

        ps._probe_dirty = False                          # consumed: this draw reflects any folded-in probes
        _shown = []
        for r in range(body_rows):
            i = ps.rtop + r
            if i >= n:
                break
            name, depth = crows[i]
            y = rit + 1 + r
            _shown.append(name)
            _parts = ps._parts(name)
            if _parts:
                _shown.extend(_parts)                    # probe a parts-aggregator's members too
            cur = i == ps.rcur
            foc = cur and ps.focus == 'right'
            avail, via, pinned = ps._resolve(name)
            istate = ps.install_state(name)             # 'all' · 'some' (parts partial) · 'none'
            installed = istate == 'all'
            _d = _disp.get(name)
            is_new = ctx.config.is_new(name)
            rev = curses.A_REVERSE if (low_color and cur and not foc) else 0
            if foc:
                _put(stdscr, y, ril, ' ' * riw, pal.fill(y, ril, h, w, selected=True))
            elif rev:
                _put(stdscr, y, ril, ' ' * riw, curses.A_REVERSE)
            nelem = ('info_dim' if not avail else 'link' if _d == 'interesting'
                     else 'menu_new' if is_new else 'info_dim' if _d == 'seen' else 'component')
            _hput(y, 0, '#' if name in ps.selected_comps else ' ',
                  pal.style('component', y, ril, h, w, selected=foc) | rev)
            if depth:
                prefix = '  ↳ '
            elif ps.is_expandable(name):
                prefix = '▾ ' if name in ps.expanded_parts else '▸ '
            else:
                prefix = '  '                            # align leaves with the twisty column
            pw = len(prefix)
            _hput(y, x_name, prefix, pal.style(nelem, y, ril + x_name, h, w, selected=foc) | rev)
            _hput(y, x_name + pw, _fit(name, max(0, name_w - pw)),
                  pal.style(nelem, y, ril + x_name + pw, h, w, selected=foc)
                  | rev | (curses.A_UNDERLINE if installed else 0))
            via_txt = (f'[{via}]' if pinned else via) if via else ('—' if not avail else '')
            _hput(y, x_via, _fit(via_txt, via_w),
                  pal.style('method_dim', y, ril + x_via, h, w, selected=foc) | rev)
            _hput(y, x_org, _fit(ps.origin(name), org_w),
                  pal.style('method_dim', y, ril + x_org, h, w, selected=foc) | rev)
            # inst'd: ⮾ staged-for-uninstall · ● installed+tracked · ⊙ installed+untracked · ◐ partial · ○ none
            if name in _uq:
                inst_g, inst_role = '⮾', 'orphan_lurking'
            elif istate == 'all':
                inst_g = '●' if name in _cur_track else '⊙'
                inst_role = 'installed' if name in _cur_track else 'orphan_lurking'
            elif istate == 'some':
                inst_g, inst_role = '◐', 'installed'
            elif not avail:                              # no install method on THIS OS
                inst_g, inst_role = '⊘', 'info_dim'
            else:
                inst_g, inst_role = '○', 'info_dim'
            cells = [(inst_g, inst_role),
                     ('◆' if is_new else ' ', 'menu_new'),
                     ('☆' if _d == 'interesting' else '·' if _d == 'seen' else ' ',
                      'link' if _d == 'interesting' else 'info_dim')]
            for (glyph, role), sx in zip(cells, st_x):
                _hput(y, sx, glyph, pal.style(role, y, ril + sx, h, w, selected=foc) | rev)
            # per-machine Included cells (● picked · ○ not, centered) — a picked target machine is bold
            for mi, m in enumerate(machines):
                picked = name in picks_map.get(m, ())
                gx = m_base[mi] + max(0, (mach_w[mi] - MGAP - 1)) // 2
                _hput(y, gx, '●' if picked else '○',
                      pal.style('installed' if picked else 'info_dim', y, ril + gx, h, w, selected=foc)
                      | rev | (curses.A_BOLD if (picked and m in tgset) else 0))
        if ps.show_install:                              # probe the just-drawn rows on non-enumerable drivers
            ps.ensure_probes(_shown)
        _scrollbar_v(stdscr, pal, rit + 1, rleft + rw - 1, body_rows, ps.rtop, body_rows, n, h, w)
        if hbar:                                          # horizontal thumb on the bottom border
            _scrollbar_h(stdscr, pal, ctop + cath - 1, ril, riw, rhoff, riw, total_w, h, w)

        status = vm.status
        if vm.note:
            status += f'    {vm.note}'
        legend1, legend2 = vm.legend1, vm.legend2
        _sty = lambda row, x: pal.style('status_line', row, x, h, w)
        lg1_x = max(0, w - len(legend1))
        lg2_x = max(0, w - len(legend2))
        _put(stdscr, h - 4, 0, _fit(status, max(1, lg1_x - 1)), _sty(h - 4, 0))
        _put(stdscr, h - 4, lg1_x, _fit(legend1, w - lg1_x), _sty(h - 4, lg1_x))
        _put(stdscr, h - 3, lg2_x, _fit(legend2, w - lg2_x), _sty(h - 3, lg2_x))
        _put(stdscr, h - 2, 0, _fit(vm.nav1.ljust(w), w), pal.style('footer', h - 2, 0, h, w))
        _put(stdscr, h - 1, 0, _fit(vm.nav2.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
        stdscr.refresh()

    # -- handle -----------------------------------------------------------

    def _redraw(self, stdscr, pal, note):
        '''The modal redraw callback (filter/find edits) — the legacy painter, exactly as before.'''
        menu._draw_profiles(stdscr, pal, self.model, self.model.ctx, note, 'profiles')

    def handle(self, ch, ctx, stdscr, pal):
        '''One key. Mutates the model, runs the modals, returns an Intent(note, dirty, pending_notes,
        open_where). Ported verbatim from the former profiles dispatch; the `machine-target` branch
        rebuilds the model (as the loop used to rebind `ps`) and swaps it in as self.model.'''
        from ... import actions
        ps = self.model
        km = menu._KEYMAP
        pfact = km.action_for('profiles', ch) if km is not None else None
        note = None
        dirty = False
        pending = []
        open_where = None
        if pfact == 'down':
            if ps.focus == 'left':
                ps.lcur = min(len(ps.visible_pnodes()) - 1, ps.lcur + 1)
            else:                              # column-major grid: down = next item, wraps col
                ps.rcur = min(len(ps.vcatalog()) - 1, ps.rcur + 1)
        elif pfact == 'up':
            if ps.focus == 'left':
                ps.lcur = max(0, ps.lcur - 1)
            else:
                ps.rcur = max(0, ps.rcur - 1)
        elif pfact == 'page-down':
            if ps.focus == 'left':
                ps.lcur = min(len(ps.visible_pnodes()) - 1, ps.lcur + _page_rows(stdscr))
            else:
                ps.rcur = min(len(ps.vcatalog()) - 1, ps.rcur + _page_rows(stdscr))
        elif pfact == 'page-up':
            if ps.focus == 'left':
                ps.lcur = max(0, ps.lcur - _page_rows(stdscr))
            else:
                ps.rcur = max(0, ps.rcur - _page_rows(stdscr))
        elif pfact in ('switch-pane', 'switch-pane-back'):
            ps.focus = 'right' if ps.focus == 'left' else 'left'   # tab / shift-tab toggle
        elif pfact == 'confirm' and ps.focus == 'left':
            _nd = ps.cur_node()
            if ps.is_group_header(_nd):        # a group header: fold/unfold it
                (ps.collapse_cur if _nd[4] else ps.expand_cur)()
            elif _nd and _nd[3]:               # expandable -> drill the tree in place (reveal subs)
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
            # orphans coloured, ignored orphans revealed dimmed). NOTE: don't invalidate the
            # overlay cache here — the data is identical on/off (only the rendering differs).
            note = ('install overlay off',
                    'install overlay ON — installed underlined, orphans coloured '
                    '(ignored dimmed)')[ps.show_install]
        elif pfact == 'stage-uninstall' and ps.focus == 'right':
            _targets = ps.action_targets()         # stage the set (else the cursor) for uninstall
            if _targets:                           # (idempotent — like Components `x`; unstage there)
                nch = 0
                try:
                    for _c in _targets:
                        if _c in ctx.config.uninstall_queue():
                            continue
                        changed, _lbl = actions.stage_uninstall(ctx, _c, on=True)
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
                        changed, _lbl = actions.set_disposition(ctx, _c, _state)
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
                        cn, _l = actions.set_included(ctx, _c, tg, on)
                        nch += cn
                    if on:                         # tracked implies seen (undispositioned -> seen)
                        actions.mark_all_seen(ctx, _targets)
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
                nch = actions.mark_all_seen(ctx, _new)
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
                        cn, _l = actions.set_included(ctx, _cc, [_m], True)
                        nch += cn
                actions.mark_all_seen(ctx, _claim)   # tracked implies seen
                ps.reload(); dirty = True
                note = f'claimed {len(_claim)} installed → tracked on {", ".join(tg)}'
        elif pfact == 'top':
            setattr(ps, 'lcur' if ps.focus == 'left' else 'rcur', 0)
        elif pfact == 'bottom':
            if ps.focus == 'left':
                ps.lcur = max(0, len(ps.visible_pnodes()) - 1)
            else:
                ps.rcur = max(0, len(ps.vcatalog()) - 1)
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
                allvis = ps.members(prof, ps.cur_ceiling()) if prof else set()
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
                mnote = _component_machines_modal(stdscr, pal, ctx, _c)
                ps.reload(); dirty = True
                note = mnote or f'{_c} machines'
        elif pfact == 'machine-target':          # target machines + add/rename/remove (modal)
            cur, mnote = _machines_modal(stdscr, pal, ctx, ps.targets())
            _keep = (ps.lcur, ps.ltop, ps.rcur, ps.rtop, ps.focus, ps.pfilter, ps.cfilter,
                     set(ps.selected_comps))
            ps = _ProfilesModel(ctx)             # rebuild against any machine add/rename/remove
            (ps.lcur, ps.ltop, ps.rcur, ps.rtop, ps.focus, ps.pfilter, ps.cfilter,
             ps.selected_comps) = _keep          # ...but keep the user where they were
            ps.target_machines = cur
            self.model = ps
            dirty = True
            note = mnote or f'targets: {", ".join(sorted(cur)) or "(none)"}'
        elif pfact == 'where':                     # full-page provenance for the current profile
            _wp = ps.cur_profile()
            if _wp:
                from ...app import where_profile_report
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
                        nch, _l = actions.set_included(ctx, name, tg, on)
                        if on:                            # tracked implies seen
                            actions.mark_all_seen(ctx, [name])
                        ps.reload()
                        dirty = dirty or nch > 0
                        note = (f'{name} {"included on" if on else "excluded from"} {", ".join(tg)}'
                                if nch else 'no change')
                    except ConfigsysError as e:
                        note = f'edit failed: {e}'
        return Intent(note=note, dirty=dirty, pending_notes=pending or None, open_where=open_where)
