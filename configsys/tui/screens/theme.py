'''theme.py — the Theme editor screen as a Screen (build_vm/draw/handle).

Migrated off the monolithic menu.py painter (docs/d2-mvvm-plan.md), mirroring the Plugins
pattern-setter. The model is the existing `menu.ThemeScreen` (the color map + per-page role state,
cursors, preview cache), composed unchanged as `_ThemeModel`; this adds the three MVVM seams:

- build_vm: reloads the model (the legacy painter reloads at the top of every frame, so the swatches
  and hexes track live edits) and computes the PURE content of the two lists — the color-map rows
  (name, rgb, override mark) and the focused page's role rows (the swatch's fg/bg rgb + effect flags,
  and the already-formatted row text), plus the page name, focus, and the edit-target label. No
  curses, no panel geometry.
- draw: lays the content out (the two top panels, the 1-or-2 column map with its stride written back
  to the model, the keep-cursor-in-view scrolls, scrollbars), paints the swatches from the VM's rgb
  values, renders the live sample slot through the shared `_sample_page` (the real page painters —
  unchanged), and the status/nav footer. It reproduces menu._draw_theme (top-level, sample=True) cell
  for cell, which test_screen_theme pins against the legacy painter. The self-preview sub-page
  (sample=False, inside _sample_real_page) keeps using the legacy painter.
- handle: the former `if screen == 'theme'` dispatch, returning an Intent(note, new_pal) — every edit
  that used to rebind the loop's `pal` now hands the rebuilt Palette to the router via `new_pal`.
'''

from .. import menu
from ..menu import (ThemeScreen as _ThemeModel, _draw_nav, _eff_flags, _fill_bg, _fit, _hex,
                    _input_box, _page_rows, _panel, _popup_choose, _put, _ref_str, _sample_page,
                    _scroll_top, _scrollbar_v, _valid_ref)
from ..theme import ALL_PAGES, Palette, parse_color
from .base import Intent, Screen, ViewModel


class ThemeVM(ViewModel):
    '''Pure render content for one Theme frame — settled by build_vm, painted by draw.'''

    def __init__(self):
        self.page = ''             # the focused sample page's name (ALL_PAGES[model.page])
        self.focus = 'map'         # 'map' | 'roles'
        # color map rows, one per model.map_names entry: (name, rgb, mark)
        self.map_rows = []
        # role rows, one per model.role_list() entry:
        #   ('grad', rgb, text)                    — a gradient endpoint pseudo-role (one color)
        #   ('role', fg_rgb, bg_rgb_or_None, effects, text)  — effects = {bold, underline, reverse}
        self.role_rows = []
        self.edit_target = ''      # where edits land (actions.edit_target label)
        self.note = ''             # the transient action note (the host supplies it; '' when none)


def _nav_str(focus):
    km = menu._KEYMAP
    if km is not None:
        g = lambda a: km.glyph('theme', a)
        if focus == 'map':
            return (f" {g('switch-pane')}→roles · {g('left')}/{g('right')}/{g('down')}/{g('up')} · "
                    f"F1-7 page · {g('confirm')} set #rrggbb · {g('new')} new · {g('reset')} remove · "
                    f"{g('save')} save · {g('load')} load · {g('quit')} ")
        return (f" {g('switch-pane')}→map · {g('down')}/{g('up')} · F1-7 page · {g('confirm')} fg · "
                f"{g('edit-bg')} bg · {g('effect-bold')}/{g('effect-underline')}/{g('effect-reverse')} fx · "
                f"{g('reset')} reset · {g('gradient-toggle')} grad · {g('copy-page')} copy-page · "
                f"{g('save')} save · {g('load')} load · {g('quit')} ")
    if focus == 'map':
        return (' tab→roles · h/l/j/k · F1-7 page · ↵ set #rrggbb · n new · x/r remove · '
                's save · L load · q ')
    return (' tab→map · j/k · F1-7 page · ↵ fg · B bg · o/u/v fx · r reset · p grad on/off · '
            'D copy-page · s save · L load · q ')


class ThemeScreen(Screen):
    id = 'theme'

    def __init__(self, ctx, model=None, sample_ms=None):
        self.ctx = ctx
        self.model = model if model is not None else _ThemeModel(ctx)
        self.sample_ms = sample_ms          # the session's live Components state (for its sample)

    def reload(self):
        self.model.reload()

    # -- build_vm ---------------------------------------------------------

    def build_vm(self, ctx, size):
        from ... import actions
        ts = self.model
        ts.reload()                          # legacy reloads at the top of every frame; build_vm
        vm = ThemeVM()                       # runs immediately before draw, so this is that spot
        vm.page = ALL_PAGES[ts.page]
        vm.focus = ts.focus
        for name in ts.map_names:
            rgb = ts.colors.get(name, (235, 235, 235))
            mark = '*' if ts.color_override(name) is not None else ' '
            vm.map_rows.append((name, rgb, mark))
        for role in ts.role_list():
            if role.startswith('@grad'):                  # a gradient endpoint: one color, no fx
                which = 'from' if role == '@grad_from' else 'to'
                mark = '*' if ts.grad_override(which) is not None else ' '
                vm.role_rows.append(('grad', ts.grad_rgb(which),
                                     f'{mark}gradient {which:5} {_ref_str(ts.grad_ref(which))}'))
                continue
            ref, rst = ts.role_ref(role), ts.role_style(role)
            eff = ''.join(c for c, f in (('b', 'bold'), ('u', 'underline'), ('r', 'reverse')) if rst.get(f))
            mark = '*' if ts.role_override(role) is not None else ' '
            txt = f'{mark}{role:14.14} {_ref_str(ref.get("fg")):>8.8}/{_ref_str(ref.get("bg")):<8.8} {eff}'
            effects = {f: bool(rst.get(f)) for f in ('bold', 'underline', 'reverse')}
            vm.role_rows.append(('role', rst['fg'], rst.get('bg') or None, effects, txt))
        vm.edit_target = actions.edit_target(ctx)[1]
        return vm

    # -- draw -------------------------------------------------------------

    def draw(self, surface, pal, vm):
        ts = self.model
        surface.erase()
        h, w = surface.getmaxyx()
        pal.use_page('theme')
        if pal.gradient:
            _fill_bg(surface, pal, h, w)
        _draw_nav(surface, pal, 'theme', h, w)
        page = vm.page
        body_h = h - 3
        list_h = min(max(9, body_h * 2 // 5), max(1, body_h - 1))  # top band: the two lists side by side; the
        mw = min(max(30, w // 2), max(1, w - 1))   # sample gets the taller rest below, FULL width (wide pages)

        # -- List 1: the shared color map (name -> #rrggbb), top-LEFT; two columns when wide enough --
        m_it, m_il, m_ih, m_iw = _panel(surface, pal, 1, 0, list_h, mw, 'color map (shared)',
                                        ts.focus == 'map', h, w)
        ncols = 2 if m_iw >= 60 else 1
        rows_per_col = max(1, -(-len(vm.map_rows) // ncols))      # ceil
        ts.map_ncols, ts.map_rows_per_col = ncols, rows_per_col
        col_w = m_iw // ncols
        nw = 12 if ncols == 2 else 14
        ts.map_top = _scroll_top(ts.map_cur % rows_per_col, ts.map_top, m_ih, rows_per_col)
        for i, (name, rgb, mark) in enumerate(vm.map_rows):
            col, row = divmod(i, rows_per_col)
            if not (ts.map_top <= row < ts.map_top + m_ih):
                continue
            y, x = m_it + (row - ts.map_top), m_il + col * col_w
            sel = i == ts.map_cur and ts.focus == 'map'
            if sel:
                _put(surface, y, x, ' ' * col_w, pal.fill(y, x, h, w, selected=True))
            _put(surface, y, x + 1, ' ██ ', pal.rgb_attr(rgb))
            _put(surface, y, x + 6, _fit(f'{mark}{name:{nw}} {_hex(rgb)}', col_w - 6),
                 pal.style('label' if sel else 'component', y, x + 6, h, w, selected=sel))
        _scrollbar_v(surface, pal, m_it, m_il + m_iw, m_ih, ts.map_top, m_ih, rows_per_col, h, w)

        # -- List 2: the focused page's role styles (top-RIGHT), plus the gradient endpoints as rows --
        roles = vm.role_rows
        ts.role_cur = min(ts.role_cur, max(0, len(roles) - 1))
        r_it, r_il, r_ih, r_iw = _panel(surface, pal, 1, mw, list_h, w - mw,
                                        _fit(f'page roles — {page}  (F1-7)', (w - mw) - 4), ts.focus == 'roles',
                                        h, w)
        ts.role_top = _scroll_top(ts.role_cur, ts.role_top, r_ih, len(roles))
        for vis, i in enumerate(range(ts.role_top, min(len(roles), ts.role_top + r_ih))):
            rr, y = roles[i], r_it + vis
            sel = i == ts.role_cur and ts.focus == 'roles'
            if sel:
                _put(surface, y, r_il, ' ' * r_iw, pal.fill(y, r_il, h, w, selected=True))
            if rr[0] == 'grad':                                    # a gradient endpoint: one color, no fx
                _put(surface, y, r_il + 1, ' ██ ', pal.rgb_attr(rr[1]))
                _put(surface, y, r_il + 6, _fit(rr[2], r_iw - 6),
                     pal.style('label' if sel else 'component', y, r_il + 6, h, w, selected=sel))
                continue
            _kind, fg, bg, effects, txt = rr
            sw = pal.rgb_pair(fg, bg) if bg else pal.rgb_attr(fg)
            _put(surface, y, r_il + 1, ' Aa ', sw | _eff_flags(effects))
            _put(surface, y, r_il + 6, _fit(txt, r_iw - 6),
                 pal.style('label' if sel else 'component', y, r_il + 6, h, w, selected=sel))
        _scrollbar_v(surface, pal, r_it, r_il + r_iw, r_ih, ts.role_top, r_ih, len(roles), h, w)

        # -- the sample page (BOTTOM, full width): a live, compressed instance of the REAL page (no outer
        # frame — the mini page brings its own nav bar / panels / footer). The top-level render is
        # always the sample=True path; the self-preview (sample=False) is the legacy painter's. --
        sy, sh = 1 + list_h, body_h - list_h
        _sample_page(surface, pal, self.ctx, ts, page, sy, 0, sh, w, self.sample_ms)
        pal.use_page('theme')

        status = f' terminal color: {pal.color_mode}   ·   edits → {vm.edit_target}'
        if vm.note:
            status += f'    {vm.note}'
        navf = _nav_str(ts.focus)
        _put(surface, h - 2, 0, _fit(status, w), pal.style('status_line', h - 2, 0, h, w))
        _put(surface, h - 1, 0, _fit(navf.ljust(w), w), pal.style('footer', h - 1, 0, h, w))
        surface.refresh()

    # -- handle -----------------------------------------------------------

    def handle(self, ch, ctx, stdscr, pal):
        '''One key. Mutates the model, runs the edit modals, returns an Intent(note, new_pal). Ported
        verbatim from the former theme dispatch: every edit that rebuilt the loop's Palette for the live
        preview now returns it as `new_pal` (None when nothing rebuilt it). Theme never marks the tree
        dirty and never changes screen.'''
        from ... import actions
        ts = self.model
        km = menu._KEYMAP
        note = None
        new_pal = None
        try:
            page = ALL_PAGES[ts.page]
            tact = km.action_for('theme', ch) if km is not None else None
            if tact in ('switch-pane', 'switch-pane-back'):
                ts.focus = 'roles' if ts.focus == 'map' else 'map'    # toggle the two lists
            elif tact in ('left', 'right'):
                left = tact == 'left'
                if ts.focus == 'map' and ts.map_ncols > 1:            # move between columns
                    step = ts.map_rows_per_col
                    ts.map_cur = (max(0, ts.map_cur - step) if left
                                  else min(len(ts.map_names) - 1, ts.map_cur + step))
                else:
                    ts.focus = 'roles' if ts.focus == 'map' else 'map'   # else cross panels
            elif tact and tact.startswith('page-') and tact[5:].isdigit():
                ts.page = min(len(ALL_PAGES) - 1, int(tact[5:]) - 1)  # F1-F7 select the sample page
            elif tact == 'down':
                if ts.focus == 'map':
                    ts.map_cur = min(len(ts.map_names) - 1, ts.map_cur + 1)
                else:
                    ts.role_cur = min(len(ts.role_list()) - 1, ts.role_cur + 1)
            elif tact == 'up':
                if ts.focus == 'map':
                    ts.map_cur = max(0, ts.map_cur - 1)
                else:
                    ts.role_cur = max(0, ts.role_cur - 1)
            elif tact == 'page-down':
                if ts.focus == 'map':
                    ts.map_cur = min(len(ts.map_names) - 1, ts.map_cur + _page_rows(stdscr))
                else:
                    ts.role_cur = min(len(ts.role_list()) - 1, ts.role_cur + _page_rows(stdscr))
            elif tact == 'page-up':
                if ts.focus == 'map':
                    ts.map_cur = max(0, ts.map_cur - _page_rows(stdscr))
                else:
                    ts.role_cur = max(0, ts.role_cur - _page_rows(stdscr))
            elif tact == 'top':
                setattr(ts, 'map_cur' if ts.focus == 'map' else 'role_cur', 0)
            elif tact == 'bottom':
                if ts.focus == 'map':
                    ts.map_cur = max(0, len(ts.map_names) - 1)
                else:
                    ts.role_cur = max(0, len(ts.role_list()) - 1)

            # -- color-map edits --
            elif ts.focus == 'map' and tact in ('select', 'confirm'):
                name = ts.cur_color()
                cur = _hex(ts.colors.get(name, (235, 235, 235)))
                new = _input_box(stdscr, pal, f'color {name}  (now {cur} → #rrggbb)', '')
                if new and new.strip():
                    if parse_color(new.strip()) is None:
                        note = f'invalid color: {new.strip()}'          # reject, don't store
                    else:
                        actions.set_theme_value(ctx, f'colors.{name}', new.strip())
                        new_pal = Palette(ctx.config.theme())
                        note = f'{name} = {new.strip()}'
            elif ts.focus == 'map' and tact == 'new':
                nm = _input_box(stdscr, pal, 'new color name', '')
                if nm and nm.strip():
                    nm = nm.strip().replace(' ', '_')
                    hexv = _input_box(stdscr, pal, f'{nm}  (#rrggbb)', '#cccccc')
                    if hexv is None or parse_color(hexv.strip()) is None:
                        note = f'invalid color — {nm} not added'
                    else:
                        actions.set_theme_value(ctx, f'colors.{nm}', hexv.strip())
                        new_pal = Palette(ctx.config.theme())
                        ts.reload()
                        if nm in ts.map_names:
                            ts.map_cur = ts.map_names.index(nm)
                        note = f'added color {nm}'
            elif ts.focus == 'map' and tact == 'reset':
                name = ts.cur_color()
                if ts.color_override(name) is None:
                    note = f'{name} is a built-in color (nothing to remove)'
                else:
                    actions.set_theme_value(ctx, f'colors.{name}', None)
                    new_pal = Palette(ctx.config.theme())
                    ts.reload()
                    note = f'{name} reset to default'

            # -- gradient endpoints (single-color pseudo-roles) --
            elif (ts.focus == 'roles' and str(ts.cur_role()).startswith('@grad')
                  and tact in ('select', 'confirm', 'reset', 'edit-bg',
                               'effect-bold', 'effect-underline', 'effect-reverse')):
                which = 'from' if ts.cur_role() == '@grad_from' else 'to'
                if tact in ('select', 'confirm'):
                    cur = ts.grad_ref(which)
                    new = _input_box(stdscr, pal,
                                     f'{page} · gradient {which}  (now {cur} → map name or #hex)',
                                     '', complete=ts.map_names)
                    if new and new.strip():
                        if not _valid_ref(new, ts.map_names):
                            note = f'invalid color/ref: {new.strip()}'
                        else:
                            actions.set_theme_value(ctx, f'pages.{page}.gradient.{which}', new.strip())
                            new_pal = Palette(ctx.config.theme())
                            note = f'gradient {which} = {new.strip()}'
                elif tact == 'reset':
                    if ts.grad_override(which) is None:
                        note = f'gradient {which} is default on {page} (nothing to reset)'
                    else:
                        actions.set_theme_value(ctx, f'pages.{page}.gradient.{which}', None)
                        new_pal = Palette(ctx.config.theme())
                        note = f'gradient {which} reset to default on {page}'
                else:                                     # B/o/u/v — endpoints are one color
                    note = 'gradient endpoints have no bg or effects'

            # -- per-page role edits --
            elif ts.focus == 'roles' and tact in ('select', 'confirm'):
                role = ts.cur_role()
                cur = _ref_str(ts.role_ref(role).get('fg'))
                new = _input_box(stdscr, pal, f'{page} · {role} · fg  (now {cur} → map name or #hex)',
                                 '', complete=ts.map_names)
                if new and new.strip():
                    if not _valid_ref(new, ts.map_names):
                        note = f'invalid color/ref: {new.strip()}'
                    else:
                        actions.set_theme_value(ctx, f'pages.{page}.{role}.fg', new.strip())
                        new_pal = Palette(ctx.config.theme())
                        note = f'{role} fg = {new.strip()}'
            elif ts.focus == 'roles' and tact == 'edit-bg':
                role = ts.cur_role()
                cur = _ref_str(ts.role_ref(role).get('bg'))
                new = _input_box(stdscr, pal, f'{page} · {role} · bg  (now {cur} → name/#hex, empty clears)',
                                 '', complete=ts.map_names)
                if new is not None:
                    if new.strip() and not _valid_ref(new, ts.map_names):
                        note = f'invalid color/ref: {new.strip()}'
                    else:
                        actions.set_theme_value(ctx, f'pages.{page}.{role}.bg', new.strip() or None)
                        new_pal = Palette(ctx.config.theme())
                        note = f'{role} bg {"set" if new.strip() else "cleared"}'
            elif ts.focus == 'roles' and tact in ('effect-bold', 'effect-underline', 'effect-reverse'):
                role = ts.cur_role()
                attr = {'effect-bold': 'bold', 'effect-underline': 'underline',
                        'effect-reverse': 'reverse'}[tact]
                on = not bool(ts.role_style(role).get(attr))
                actions.set_theme_value(ctx, f'pages.{page}.{role}.{attr}', on)
                new_pal = Palette(ctx.config.theme())
                note = f'{role} {attr} {"on" if on else "off"}'
            elif ts.focus == 'roles' and tact == 'reset':
                role = ts.cur_role()
                if ts.role_override(role) is None:
                    note = f'{role} is default on {page} (nothing to reset)'
                else:
                    actions.set_theme_value(ctx, f'pages.{page}.{role}', None)
                    new_pal = Palette(ctx.config.theme())
                    ts.reload()
                    note = f'{role} reset to default on {page}'

            elif tact == 'gradient-toggle':               # from/to now live in the role list
                on = not ts.page_gradient_enabled(page)
                actions.set_theme_value(ctx, f'pages.{page}.gradient.enabled', on)
                new_pal = Palette(ctx.config.theme())
                note = f'{page} gradient {"on" if on else "off"}'
            elif tact == 'copy-page':                     # copy this page's look onto another
                others = [p for p in ALL_PAGES if p != page]
                di = _popup_choose(stdscr, pal, f'copy {page}’s theme onto…',
                                   [(p, '') for p in others], 0)
                if di is not None:
                    ok, label = actions.copy_page_theme(ctx, page, others[di])
                    if ok:
                        new_pal = Palette(ctx.config.theme())
                        note = f'copied {page} → {others[di]}'
                    else:
                        note = label
            elif tact == 'save':
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
                        new_pal = Palette(ctx.config.theme())
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
            elif tact == 'load':
                names = actions.theme_plugins(ctx)
                if names:
                    idx = _popup_choose(stdscr, pal, 'load theme', [(n, '') for n in names], 0)
                    if idx is not None:
                        actions.load_theme(ctx, names[idx])
                        new_pal = Palette(ctx.config.theme())
                        note = f'loaded {names[idx]}'
                else:
                    note = 'no theme plugins saved yet (s to save one)'
        except Exception as e:  # noqa: BLE001 — surface, don't crash
            note = f'error: {e}'
        return Intent(note=note, new_pal=new_pal)
