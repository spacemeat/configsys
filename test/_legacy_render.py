'''Frozen pre-refactor TUI painters — the render-equivalence ORACLE for the D2 MVVM rewrite
(docs/d2-mvvm-plan.md). The app no longer uses these; each new Screen.draw is pinned cell-for-cell
against the matching function here (test_screen_*.py). They will be retired once the screens carry
standalone fake-data render tests. DO NOT EDIT — this is the baseline the migration was proven against.

Every helper/constant/model these bodies reference is pulled from configsys.tui.menu (functions +
constants are stable); the one runtime-rebound global, _KEYMAP, is referenced as menu._KEYMAP so the
legends read the live keymap exactly as the originals did.'''

from configsys.tui import menu
globals().update({k: v for k, v in vars(menu).items() if not k.startswith('__')})
curses = menu.curses


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
    if screen == 'components':                        # which view MODE the tree is showing (M cycles)
        sub += f'   view: {getattr(ms, "mode", "to-do")}'
    _put(stdscr, 1, len(title), _fit(sub, max(1, w - len(title))), pal.style('os', 1, len(title), h, w))
    rend = len(title) + len(sub)
    if screen == 'components':                       # package-index staleness, right of the OS tag
        from configsys import refreshstate
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
        reb = getattr(ctx, '_reboot_pending', None)   # (reboot, reason) cached at build/execute
        if reb and reb[0]:
            btext = '  ⚠ reboot advised'
            if rend + len(btext) < w - 1:
                _put(stdscr, 1, rend, btext, pal.style('issue_warning', 1, rend, h, w))
                rend += len(btext)
    if diags:                                        # attention badge, right-aligned on the title line
        n = len(diags)
        elem = 'issue_error' if any(d['level'] == 'error' for d in diags) else 'issue_warning'
        badge = f' ⚠ {n} issue{"s" if n != 1 else ""} — press ! to view '
        bx = max(rend + 2, w - len(badge) - 1)
        _put(stdscr, 1, bx, _fit(badge, w - bx), pal.style(elem, 1, bx, h, w))

    for c, text in (('name', 'component'), ('driver', 'driver'), ('scope', 'scope'),
                    ('status', 'status'), ('inst', 'installed'), ('latest', 'latest')):
        x, cw = cols[c]
        _put(stdscr, 2, x, _fit(text, cw), pal.style('menu_header', 2, x, h, w))

    list_top = 3
    list_h = max(1, h - list_top - 6)  # description + methods + infoblock + status + 2 footers
    if ms.reveal is not None:                        # a just-expanded node -> reveal its subtree
        pi = next((i for i, n in enumerate(ms.rows) if n.id == ms.reveal), None)
        if pi is not None:
            pd, end = ms.rows[pi].depth, pi
            for j in range(pi + 1, len(ms.rows)):
                if ms.rows[j].depth > pd:
                    end = j
                else:
                    break
            ms.top = _scroll_reveal(pi, end, ms.top, list_h, len(ms.rows))
        ms.reveal = None
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
    if menu._KEYMAP is not None:                          # legends read the live keymap (rebinds show here)
        g = lambda a: menu._KEYMAP.glyph('components', a)   # components scope, falling back to global
        nav = (f" {g('down')}/{g('up')} move · {g('top')}/{g('bottom')} top/bottom · "
               f"{g('right')}/{g('left')} expand/collapse · {g('confirm')} open · {g('find')} find · "
               f"{g('filter')} filter · {g('expand-all')} expand-all ")
        act = (f" {g('select')} sel · {g('select-all')} all · {g('op-install')}/{g('op-install-all')} inst · "
               f"{g('op-upgrade')}/{g('op-upgrade-all')} upg · {g('op-remove')} rm · {g('lock')} lock · "
               f"{g('method')} via · {g('where')} where · {g('clear')} clear · {g('execute')} exec · "
               f"{g('refresh')} refresh · {g('issues')} issues · {g('quit')} quit ")
    else:
        nav = ' j/k · g/G top/bottom · l/h expand/collapse · enter open · / find · F filter · tab expand-all '
        act = ' space sel · a all · i/I inst · u/U upg · x rm · L lock · v via · w where · c clear · X exec · R refresh · ! issues · q quit '
    _put(stdscr, h - 3, 0, _fit(status_line, w), pal.style('status_line', h - 3, 0, h, w))
    _put(stdscr, h - 2, 0, _fit(nav.ljust(w), w), pal.style('footer', h - 2, 0, h, w))
    _put(stdscr, h - 1, 0, _fit(act.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
    stdscr.refresh()
    return diag_top

def _draw_profiles(stdscr, pal, ps, ctx, note, screen):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    pal.use_page(screen)
    if pal.gradient:
        _fill_bg(stdscr, pal, h, w)
    _draw_nav(stdscr, pal, screen, h, w)

    top, body_h = 1, max(1, h - 5)                   # TWO status/legend rows, then TWO nav rows below
    lw = max(16, w // 6) + 6                          # profiles pane: narrow, leaving the grid room (+6 cols)
    rleft, rw = lw + 1, w - lw - 1
    prof = ps.cur_curate()                           # the selected profile
    _ceil = ps.cur_ceiling()                          # per-layer read: a system row shows pristine members
    members = ps.members(prof, _ceil)
    own = ps.own_members(prof, _ceil)                # direct (●) vs via-include (↳)
    removed = ps.removed_members(prof, _ceil)        # ~term drops (~) for the selected profile
    _disp = ctx.config.dispositions()                # {comp: seen|interesting} for the catalog markers
    ov_inst, ov_orph, ov_uninst = ps.overlay()       # install-axis overlay data (empty unless `O` on)
    # row-tint backgrounds derived from the theme's selection colour: a dimmer bar marks the current
    # row of the UNFOCUSED pane (so the profile stays visible while you navigate components), and a
    # subtle tint marks the components that are members of the selected profile.
    _sel = pal.sel_bg_rgb
    residual_bg = tuple(round(_sel[i] * 0.55) for i in range(3))
    member_bg = tuple(round(_sel[i] * 0.28) for i in range(3))
    low_color = not pal.have256    # 8/16-colour has no room for a dim tint -> those quantize to black
                                   # (invisible); reverse-video the unfocused-current row instead.

    # LEFT: profiles as a tree — top-level + inline `+include` children
    vnodes = ps.visible_pnodes()
    ltitle = 'profiles' + (f'  filter:{ps.pfilter}' if ps.pfilter else '')
    lit, lil, lih, liw = _panel(stdscr, pal, top, 0, body_h, lw, ltitle,
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
        if kind == 'group':                           # a layer-group header row (▾/▹ LABEL (count) ⁺new ☆int)
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
        # scope marker: ▸ on the row the catalog is currently scoped to (the selected one, `*` mode on)
        scope = '▸' if i == ps.lcur else ' '         # marks the profile the catalog is showing
        prefix = list(f'{scope}{"  " * depth}{exp}')
        # Exclusion attribution: for a subprofile a `~`-excluded by an ancestor on its path, paint a
        # `~` in THAT ancestor's status-glyph column (2 + 2*ancestor_depth), which falls in this row's
        # blank indent gutter — so the marker sits under the profile that's at fault. Two ancestors
        # both excluding -> two `~`s. A struck node is dimmed (it's pruned from that top-level profile).
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
        # `⁺N` counts NEW (untriaged) members; `☆N` counts INTERESTING (bookmarked) members — a
        # profile's whole worth-a-look signal (there is no active/clone state in the matrix model).
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

    # RIGHT TOP: detail for the highlighted component (names are esoteric) — description + methods
    crows = ps._catalog_rows()                        # [(name, depth)] — parts children interleaved
    vcat = [nm for nm, _dep in crows]
    cur = vcat[ps.rcur] if vcat and 0 <= ps.rcur < len(vcat) else None
    # the component NAME rides the panel title, so the box is short (2 desc lines + a "required by"
    # line + an "in profiles" line) and the catalog grid below gets the reclaimed rows.
    desc_h = 8 if body_h >= 13 else 0    # one extra inner row for the parts/requires ("needs") line
    # When the PROFILE pane is focused on a profile, the detail box shows that profile's RAW .hu
    # DEFINITION — its top (highest-precedence) layer's authored term list, e.g. `[ "^languages"
    # +jvm-lang ]` — so you see what the profile IS while navigating; a note names lower layers.
    _defs = ctx.config.profile_layer_defs(prof) if (desc_h and ps.focus == 'left' and prof) else []
    if _defs:
        # per-layer pane: read the def AT the row's group, and title it browse-only for a system row
        _grp = ps.cur_group()
        _rowdef = next((d for d in _defs if ps._fold_role(d['role']) == _grp), _defs[-1]) if _grp else _defs[-1]
        _ro = ' · browse-only' if ps.cur_readonly() else ''
        dit, dil, dih, diw = _panel(stdscr, pal, top, rleft, desc_h, rw,
                                    f'profile: {prof}  [{_rowdef["role"]}{_ro}]', False, h, w)
        top_def = _rowdef                                     # show THIS layer's authored terms
        # render terms AS AUTHORED: `^`-terms are quoted in the .hu (`^` is humon's heredoc sigil)
        shown = [f'"{t}"' if str(t).startswith('^') else str(t) for t in top_def['terms']]
        body = '[ ' + '  '.join(shown) + ' ]' if shown else '[ ]'
        for k, line in enumerate(_wordwrap(body, diw)[:dih - 1]):
            _put(stdscr, dit + k, dil, _fit(line, diw), pal.style('info', dit + k, dil, h, w))
        if len(_defs) > 1:                                    # name the lower layers that also define it
            _layer_note = '(also in: ' + ', '.join(d['role'] for d in _defs[:-1]) + ')'
            _put(stdscr, dit + dih - 1, dil, _fit(_layer_note, diw),  # own local — must NOT clobber the
                 pal.style('method_dim', dit + dih - 1, dil, h, w))   # `note` param (the action feedback)
    elif desc_h:
        dit, dil, dih, diw = _panel(stdscr, pal, top, rleft, desc_h, rw, cur or 'component', False, h, w)
        if cur:
            comp = ctx.routes.components.get(cur)
            desc = (comp.description if comp else '') or '(no description yet)'
            # A component with NO install method on THIS OS gets a warn banner on its own row (role
            # issue_warning), stealing one description row — so the moot-but-informative deps line
            # below still shows (the user wants both, not either/or).
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
            # What this component PULLS IN — the pieces of a `via: parts` aggregator, else its
            # `requires:` deps — each annotated with the method it resolves to ([*via] = pinned), so
            # you can see the composition without tracking it (and, expanded in the catalog, pin a
            # piece's driver). Capabilities (non-component requires) show plain. Always shown, even
            # when unavailable (the banner above says the whole thing won't route here).
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

    # RIGHT BOTTOM: the component catalog as a single vertical TABLE (the v3 matrix) — one row per
    # component: name · origin · state columns (installed · included-on-target · new · flag) · one
    # Included cell PER machine. A/D toggle Included on the selected TARGET machines.
    ctop, cath = top + desc_h, body_h - desc_h
    machines = ps.machines_list()
    tgset = ps.targets()
    picks_map = ctx.config.picks()
    _uq = ctx.config.uninstall_queue()               # staged-for-uninstall -> ⮾ in the inst'd column
    _cur_track = ctx.config.included()               # tracked on THIS box -> ● vs ⊙ (installed-untracked)
    ctitle = ((f'components — in "{prof}"' if prof else 'components')
              + (f'  filter:{ps.cfilter}' if ps.cfilter else '')
              + ('  #sel:' + str(len(ps.selected_comps)) if ps.selected_comps else '')
              + ps.attr_summary())
    rit, ril, rih, riw = _panel(stdscr, pal, ctop, rleft, cath, rw, ctitle, ps.focus == 'right', h, w)
    n = len(vcat)
    body_rows = max(1, rih - 1)                       # one row reserved for the column header
    ps.rcur = min(ps.rcur, max(0, n - 1))
    ps.rtop = _scroll_top(ps.rcur, ps.rtop, body_rows, n)
    # column layout (fixed offsets from ril): sel · name · via · from · state cols · machine cols.
    # The whole table scrolls horizontally (rhoff, driven by ←/→) when it's wider than the pane;
    # each wide-glyph state column is word-headed and holds its glyph at the column's left edge.
    STATE = [("inst'd", 7), ('new', 4), ('flag', 5)]   # tracked is the per-machine cells (below), not a col
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
            _shown.extend(_parts)                    # probe a parts-aggregator's members so it can read installed
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
        # expandable `via: parts` rows get a ▸/▾ twisty; drilled-in parts are indented under them.
        # The twisty/indent is drawn WITHOUT the installed-underline so the underline hugs the name.
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
        # state cells — wide glyphs (each at the column's left edge, with a trailing gap so it renders).
        # inst'd: ⮾ staged-for-uninstall · ● installed+tracked · ⊙ installed+untracked · ◐ partial · ○ none
        if name in _uq:
            inst_g, inst_role = '⮾', 'orphan_lurking'
        elif istate == 'all':
            inst_g = '●' if name in _cur_track else '⊙'
            inst_role = 'installed' if name in _cur_track else 'orphan_lurking'
        elif istate == 'some':
            inst_g, inst_role = '◐', 'installed'
        elif not avail:                              # no install method on THIS OS -> can't install here
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

    _tg = sorted(ps.targets())
    status = (f' browse: {prof or "—"}    this box: {ctx.config.current_machine()}'
              f'    targets: {", ".join(_tg) or "(none)"}')
    if note:
        status += f'    {note}'
    # column legend for the matrix table — two right-aligned rows (status shares the first row's left).
    legend1 = "inst'd  ● trk  ⊙ untrk  ◐ part  ○ no  ⮾ uninst  ⊘ n/a-here "
    legend2 = "flag  ☆ int  · seen    new  ◆    machine  ● tracked  ○ not    tree  ⊙ N "
    _sty = lambda row, x: pal.style('status_line', row, x, h, w)
    lg1_x = max(0, w - len(legend1))
    lg2_x = max(0, w - len(legend2))
    _put(stdscr, h - 4, 0, _fit(status, max(1, lg1_x - 1)), _sty(h - 4, 0))
    _put(stdscr, h - 4, lg1_x, _fit(legend1, w - lg1_x), _sty(h - 4, lg1_x))
    _put(stdscr, h - 3, lg2_x, _fit(legend2, w - lg2_x), _sty(h - 3, lg2_x))
    if menu._KEYMAP is not None:
        g = lambda a: menu._KEYMAP.glyph('profiles', a)
        nav1 = (f" {g('down')}/{g('up')} move · {g('right')}/{g('left')} scroll/expand · "
                f"{g('switch-pane')} panes · {g('find')} find · {g('filter')} filter · "
                f"{g('attr-filter')} attrs · {g('machine-target')} machines ")
        nav2 = (f" {g('track-all')} track-set · {g('track-one')} track-one · {g('disp-interesting')} int · "
                f"{g('disp-seen')} seen · {g('select')} sel · {g('select-all')} all · "
                f"{g('method')} via · {g('stage-uninstall')} uninst · {g('quit')} quit ")
    else:
        nav1 = (' j/k move · h/l scroll/expand · tab panes · / find · F filter · f attrs · M machines ')
        nav2 = (' T track-set · t track-one · i int · s seen · space sel · a all · v via · x uninst · q quit ')
    _put(stdscr, h - 2, 0, _fit(nav1.ljust(w), w), pal.style('footer', h - 2, 0, h, w))
    _put(stdscr, h - 1, 0, _fit(nav2.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
    stdscr.refresh()

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

    # aligned columns (lowercase headers, like the Plugins table); the description + man ref wrap on
    # the rows below each setting. Column x-offsets are relative to the panel interior `il`. `store`
    # takes the remainder (it holds a path, so it wants the room); `value` got +3 for driver-preference.
    nx, vx = 0, min(18, iw // 4)
    dx = min(vx + 27, iw - 24)
    ex = min(dx + 9, iw - 15)
    nw, vw, dw = vx - 1, dx - vx - 1, ex - dx - 1
    ew = max(6, iw - ex - 1)

    import os
    from configsys import plugins as _pl
    has_primary = bool(_pl.primary_name(_pl.declared(ctx.paths.user_config_file)))
    _home = os.path.expanduser('~')

    def _homed(p):
        p = str(p)
        return '~' + p[len(_home):] if _home and p.startswith(_home) else p

    def col(y, cx, text, cw, role, sel):
        if 0 <= cx < iw - 1:
            _put(stdscr, y, il + cx, _fit(text, min(cw, iw - cx - 1)),
                 pal.style(role, y, il + cx, h, w, selected=sel))

    def _state(info):
        '''(text, role) for the `default` column — is this the built-in default, a config override,
        or an env override (which supersedes config)?'''
        if isinstance(info.get('source'), str) and info['source'].startswith('env '):
            return 'env', 'outdated'                      # amber: an environment override wins
        if info.get('home') in ('local', 'primary'):
            return 'custom', 'installed'                  # green: you've set it
        return 'default', 'info_dim'                      # dim: the built-in default

    def _store(info):
        '''(name, suffix, role) for the `store` column — the NORMALIZED location the value lives /
        edits land: "<plugin> (primary plugin)" or "<~-path> (machine-local)". The suffix always shows
        (the name truncates first). A location that differs from this setting's NATURE-DEFAULT store —
        a moved setting, or an env override that supersedes config — is highlighted; otherwise dimmed.'''
        nature = info.get('nature', 'uniform')
        default_type = 'primary' if (nature == 'uniform' and has_primary) else 'local'
        src = info.get('source')
        if isinstance(src, str) and src.startswith('env '):
            return src[4:], '(env override)', 'header'   # env supersedes config -> non-default store
        home, tgt = info.get('home'), info.get('target')
        if home == 'primary' or (home is None and tgt and tgt != 'top config'):
            pname = info.get('home_label') if home == 'primary' else tgt
            name, suffix, loc_type = pname, '(primary plugin)', 'primary'
        else:
            name, suffix, loc_type = _homed(ctx.paths.user_config_file), '(machine-local)', 'local'
        return name, suffix, ('header' if loc_type != default_type else 'scope')   # header = relocated

    def col_store(y, cx, name, suffix, cw, role, sel):
        '''Draw the store cell, keeping the (suffix) visible — the descriptor matters more than the
        long path, so the name truncates first.'''
        if len(name) + 1 + len(suffix) <= cw or cw <= len(suffix) + 4:
            txt = _fit(f'{name} {suffix}', cw)
        else:
            txt = f'{_fit(name, cw - len(suffix) - 1)} {suffix}'
        col(y, cx, txt, cw, role, sel)

    def block_h(i):
        info = cs.settings[cs.keys[i]]
        return 1 + len(_wordwrap(info['desc'], iw - 4)) + 1 + 1   # cols + desc + man + gap row

    avail = ih - 1                                        # header row consumes one
    if cs.cur < cs.top:
        cs.top = cs.cur
    while cs.top < cs.cur and sum(block_h(i) for i in range(cs.top, cs.cur + 1)) > avail:
        cs.top += 1                                       # keep the cursor's block in view

    # header row (lowercase column names)
    for cx, cw, label in ((nx, nw, 'name'), (vx, vw, 'value'), (dx, dw, 'default'), (ex, ew, 'store')):
        col(it, cx, label, cw, 'menu_header', False)

    y, shown = it + 1, 0
    for i in range(cs.top, len(cs.keys)):
        bh = block_h(i)
        if y + bh - 1 > it + ih:                          # the whole block wouldn't fit
            break
        key, info, sel = cs.keys[i], cs.settings[cs.keys[i]], i == cs.cur
        if sel:
            _put(stdscr, y, il, ' ' * iw, pal.fill(y, il, h, w, selected=True))
        st_txt, st_role = _state(info)
        s_name, s_suffix, s_role = _store(info)
        col(y, nx, key, nw, 'label' if sel else 'component', sel)
        col(y, vx, _setting_str(info['kind'], info['value'], key), vw, 'scope_choice', sel)
        col(y, dx, st_txt, dw, st_role, sel)
        col_store(y, ex, s_name, s_suffix, ew, s_role, sel)
        dy = y + 1
        for line in _wordwrap(info['desc'], iw - 4):      # word-wrapped description, not cut off
            _put(stdscr, dy, il + 3, _fit(line, iw - 4), pal.style('info_dim', dy, il, h, w))
            dy += 1
        _put(stdscr, dy, il + 3, _fit(f'man: {info["man"]}', iw - 4),  # man ref — its own colour
             pal.style('method_dim', dy, il, h, w))
        y += bh
        shown += 1
    _scrollbar_v(stdscr, pal, it + 1, il + iw, ih - 1, cs.top, max(1, shown), len(cs.keys), h, w)
    from configsys import actions
    cur_key = cs.keys[cs.cur] if cs.keys else None
    tgt = cs.settings.get(cur_key, {}).get('target') if cur_key else None
    status = f' {cur_key}: edits → {tgt}' if tgt else f' edits → {actions.edit_target(ctx)[1]}'
    if note:
        status += f'    {note}'
    if menu._KEYMAP is not None:
        g = lambda a: menu._KEYMAP.glyph('config', a)
        navf = (f" {g('down')}/{g('up')} move · {g('confirm')} edit · {g('move')} local↔primary · "
                f"{g('theme')} theme · {g('quit')} quit ")
    else:
        navf = ' j/k move · enter/space edit · m local↔primary · t theme · q quit '
    _put(stdscr, h - 2, 0, _fit(status, w), pal.style('status_line', h - 2, 0, h, w))
    _put(stdscr, h - 1, 0, _fit(navf.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
    stdscr.refresh()

def _draw_theme(stdscr, pal, ts, ctx, note, screen, ms=None, sample=True):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    pal.use_page('theme')
    if pal.gradient:
        _fill_bg(stdscr, pal, h, w)
    _draw_nav(stdscr, pal, 'theme', h, w)
    ts.reload()
    from configsys.tui.theme import ALL_PAGES
    page = ALL_PAGES[ts.page]
    body_h = h - 3
    list_h = min(max(9, body_h * 2 // 5), max(1, body_h - 1))  # top band: the two lists side by side; the
    mw = min(max(30, w // 2), max(1, w - 1))   # sample gets the taller rest below, FULL width (wide pages)

    # -- List 1: the shared color map (name -> #rrggbb), top-LEFT; two columns when wide enough --
    m_it, m_il, m_ih, m_iw = _panel(stdscr, pal, 1, 0, list_h, mw, 'color map (shared)',
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

    # -- List 2: the focused page's role styles (top-RIGHT), plus the gradient endpoints as rows --
    roles = ts.role_list()
    ts.role_cur = min(ts.role_cur, max(0, len(roles) - 1))
    r_it, r_il, r_ih, r_iw = _panel(stdscr, pal, 1, mw, list_h, w - mw,
                                    _fit(f'page roles — {page}  (F1-7)', (w - mw) - 4), ts.focus == 'roles',
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

    # -- the sample page (BOTTOM, full width): a live, compressed instance of the REAL page (no outer
    # frame — the mini page brings its own nav bar / panels / footer). Full width so wide pages
    # (Profiles' matrix, the plugins diff) preview without truncation. `sample=False` means THIS render
    # IS a sample (in the Theme-page preview) — suppress the inner slot so it doesn't recurse. --
    sy, sh = 1 + list_h, body_h - list_h
    if sample:
        _sample_page(stdscr, pal, ctx, ts, page, sy, 0, sh, w, ms)
        pal.use_page('theme')
    else:
        for yy in range(sy, sy + sh):                      # dim the slot; a hint reads "the sample goes here"
            _put(stdscr, yy, 0, ' ' * w, pal.style('unit', yy, 0, h, w))
        hint = '· live sample ·'
        _put(stdscr, sy + sh // 2, max(0, (w - len(hint)) // 2), _fit(hint, w),
             pal.style('info_dim', sy + sh // 2, 0, h, w))

    from configsys import actions
    status = f' terminal color: {pal.color_mode}   ·   edits → {actions.edit_target(ctx)[1]}'
    if note:
        status += f'    {note}'
    if menu._KEYMAP is not None:
        g = lambda a: menu._KEYMAP.glyph('theme', a)
        if ts.focus == 'map':
            navf = (f" {g('switch-pane')}→roles · {g('left')}/{g('right')}/{g('down')}/{g('up')} · "
                    f"F1-7 page · {g('confirm')} set #rrggbb · {g('new')} new · {g('reset')} remove · "
                    f"{g('save')} save · {g('load')} load · {g('quit')} ")
        else:
            navf = (f" {g('switch-pane')}→map · {g('down')}/{g('up')} · F1-7 page · {g('confirm')} fg · "
                    f"{g('edit-bg')} bg · {g('effect-bold')}/{g('effect-underline')}/{g('effect-reverse')} fx · "
                    f"{g('reset')} reset · {g('gradient-toggle')} grad · {g('copy-page')} copy-page · "
                    f"{g('save')} save · {g('load')} load · {g('quit')} ")
    elif ts.focus == 'map':
        navf = (' tab→roles · h/l/j/k · F1-7 page · ↵ set #rrggbb · n new · x/r remove · '
                's save · L load · q ')
    else:
        navf = (' tab→map · j/k · F1-7 page · ↵ fg · B bg · o/u/v fx · r reset · p grad on/off · '
                'D copy-page · s save · L load · q ')
    _put(stdscr, h - 2, 0, _fit(status, w), pal.style('status_line', h - 2, 0, h, w))
    _put(stdscr, h - 1, 0, _fit(navf.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
    stdscr.refresh()

def _draw_plugins_table(stdscr, pal, pl, h, w, top, table_h):
    from configsys import plugins
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
    from configsys import plugins
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
    if menu._KEYMAP is not None:
        g = lambda a: menu._KEYMAP.glyph('plugins', a)
        navf = (f" {g('switch-pane')} focus · {g('down')}/{g('up')} · {g('left')}/{g('right')} scroll · "
                f"{g('add')} add · {g('remove')} rm · {g('sync')}/{g('sync-all')} sync · "
                f"{g('bless')}/{g('unbless')} bless · {g('update')}/{g('update-all')} update · "
                f"{g('set-ref')} ref · {g('trust')} trust · {g('trust-all')} trust-all · {g('quit')} ")
    else:
        navf = (' tab focus · j/k · h/l scroll · a add · x rm · s/S sync · b/B bless · u/U update · '
                'v ref · t trust · T trust-all · q ')
    _put(stdscr, h - 2, 0, _fit(status, w), pal.style('status_line', h - 2, 0, h, w))
    _put(stdscr, h - 1, 0, _fit(navf.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
    stdscr.refresh()

def _draw_glue(stdscr, pal, gs, ctx, note, screen):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    pal.use_page(screen)
    if pal.gradient:
        _fill_bg(stdscr, pal, h, w)
    _draw_nav(stdscr, pal, screen, h, w)
    it, il, ih, iw = _panel(stdscr, pal, 1, 0, h - 3, w, 'glue (shell integration)', True, h, w)
    if not gs.display:
        _put(stdscr, it, il, _fit('   '.join(_GLUE_HEADERS), iw), pal.style('menu_header', it, il, h, w))
        _put(stdscr, it + 1, il, _fit('(no installed shells / no glue in the install set)', iw),
             pal.style('info_dim', it + 1, il, h, w))
    else:
        cells_by_row = [_glue_cells(r) for r in gs.rows]
        widths = [max(len(_GLUE_HEADERS[c]), max((len(cs[c]) for cs in cells_by_row), default=0))
                  for c in range(len(_GLUE_HEADERS))]
        xs, vx = [], 0
        for wd in widths:
            xs.append(vx)
            vx += wd + 2
        virt_w = vx - 2
        has_hbar = virt_w > iw
        rows_h = ih - 1 - (1 if has_hbar else 0)
        gs.hscroll = max(0, min(gs.hscroll, max(0, virt_w - iw)))
        for hdr, vx0 in zip(_GLUE_HEADERS, xs):
            _put_hscroll(stdscr, it, il, iw, vx0, gs.hscroll, hdr, pal.style('menu_header', it, il, h, w))
        disp = gs.display
        cur_disp = next((d for d, e in enumerate(disp) if e == ('row', gs.cur)), 0)
        gs.top = _scroll_top(cur_disp, gs.top, rows_h, len(disp))
        for vis, d in enumerate(range(gs.top, min(len(disp), gs.top + rows_h))):
            y = it + 1 + vis
            entry = disp[d]
            if entry[0] == 'hdr':                # a per-shell section header + its loader status
                _, shell, lstate = entry
                lbl = (_GLUE_STATE_LABEL.get(lstate, lstate) if lstate else 'not wired')
                rule = f'{shell}  loader: {lbl} '
                rule += '─' * max(0, iw - len(rule))
                _put(stdscr, y, il, _fit(rule, iw), pal.style('menu_header', y, il, h, w))
                continue
            i, sel = entry[1], entry[1] == gs.cur
            if sel:
                _put(stdscr, y, il, ' ' * iw, pal.fill(y, il, h, w, selected=True))
            elem = 'label' if sel else _DF_STATE_ELEM.get(gs.rows[i][3], 'component')
            style = pal.style(elem, y, il, h, w, selected=sel)
            for cell, wd, vx0 in zip(cells_by_row[i], widths, xs):
                _put_hscroll(stdscr, y, il, iw, vx0, gs.hscroll, cell.ljust(wd), style)
        _scrollbar_v(stdscr, pal, it + 1, il + iw, rows_h, gs.top, rows_h, len(disp), h, w)
        if has_hbar:
            _scrollbar_h(stdscr, pal, it + ih - 1, il, iw, gs.hscroll, iw, virt_w, h, w)

    n_active = sum(1 for r in gs.rows if r[3] in ('linked', 'loader-on'))
    n_changed = sum(1 for r in gs.rows if r[3] == 'drifted')
    n_inactive = len(gs.rows) - n_active - n_changed
    status = f' {len(gs.rows)} glue snippet(s)   {n_active} active'
    if n_changed:
        status += f'   {n_changed} changed (A to re-activate)'
    status += f'   {n_inactive} inactive'
    if note:
        status += f'    {note}'
    if menu._KEYMAP is not None:
        g = lambda a: menu._KEYMAP.glyph('glue', a)
        navf = (f" {g('down')}/{g('up')} · {g('left')}/{g('right')} scroll · {g('activate')} activate · "
                f"{g('activate-group')} activate group · {g('deactivate')} deactivate · {g('quit')} ")
    else:
        navf = ' j/k · h/l scroll · a activate · A activate group · x deactivate · q '
    _put(stdscr, h - 2, 0, _fit(status, w), pal.style('status_line', h - 2, 0, h, w))
    _put(stdscr, h - 1, 0, _fit(navf.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
    stdscr.refresh()

def _draw_dotfiles(stdscr, pal, ds, ctx, note, screen):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    pal.use_page(screen)
    if pal.gradient:
        _fill_bg(stdscr, pal, h, w)
    _draw_nav(stdscr, pal, screen, h, w)
    it, il, ih, iw = _panel(stdscr, pal, 1, 0, h - 3, w, 'dotfiles (config state)', True, h, w)
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
        # scroll over the DISPLAY list (group headers + rows); the cursor tracks the actionable row.
        disp = ds.display
        cur_disp = next((d for d, e in enumerate(disp) if e == ('row', ds.cur)), 0)
        ds.top = _scroll_top(cur_disp, ds.top, rows_h, len(disp))
        for vis, d in enumerate(range(ds.top, min(len(disp), ds.top + rows_h))):
            y = it + 1 + vis
            etype, val = disp[d]
            if etype == 'hdr':                   # a group divider (drawn inline, non-selectable)
                rule = f'{val} '
                rule += '─' * max(0, iw - len(rule))
                _put(stdscr, y, il, _fit(rule, iw), pal.style('menu_header', y, il, h, w))
                continue
            i, sel = val, val == ds.cur
            if sel:
                _put(stdscr, y, il, ' ' * iw, pal.fill(y, il, h, w, selected=True))
            from configsys.drivers.dotfiles import config_display_state
            elem = 'label' if sel else _DF_STATE_ELEM.get(
                config_display_state(ds.rows[i][3], ds.rows[i][5]), 'component')
            style = pal.style(elem, y, il, h, w, selected=sel)
            for cell, wd, vx0 in zip(cells_by_row[i], widths, xs):
                _put_hscroll(stdscr, y, il, iw, vx0, ds.hscroll, cell.ljust(wd), style)
        _scrollbar_v(stdscr, pal, it + 1, il + iw, rows_h, ds.top, rows_h, len(disp), h, w)
        if has_hbar:
            _scrollbar_h(stdscr, pal, it + ih - 1, il, iw, ds.hscroll, iw, virt_w, h, w)

    from configsys.drivers.dotfiles import config_display_state
    counts = {}
    for r in ds.rows:
        s = config_display_state(r[3], r[5])
        counts[s] = counts.get(s, 0) + 1
    n_risk = sum(1 for r in ds.rows if r[3] == 'unmanaged')          # a real file we don't manage
    status = (f' {len(ds.rows)} config target(s)   '
              + '   '.join(f'{counts[s]} {s}' for s in ('managed', 'unmanaged', 'no config') if counts.get(s)))
    if n_risk:
        status += f'   ! {n_risk} unmanaged file(s) at risk — capture (c) before linking'
    if note:
        status += f'    {note}'
    if menu._KEYMAP is not None:
        g = lambda a: menu._KEYMAP.glyph('dotfiles', a)
        navf = (f" {g('manage')}/{g('manage-all')} manage · {g('unmanage')}/{g('unmanage-all')} unmanage · "
                f"{g('move-store')}/{g('move-store-all')} move store · {g('quit')} ")
    else:
        navf = ' m/M manage · u/U unmanage · s/S move store · h/l scroll · q '
    _put(stdscr, h - 2, 0, _fit(status, w), pal.style('status_line', h - 2, 0, h, w))
    _put(stdscr, h - 1, 0, _fit(navf.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
    stdscr.refresh()
