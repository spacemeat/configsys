'''theme.py — color for the TUI, 24-bit when the terminal allows it.

The model is two tiers (see docs/theme-redesign.md):

- a **palette**: a name -> full STYLE map `{ fg, bg, bold, underline, reverse }` (fg/bg are
  literal colors: hex / `#rgb` / `[r,g,b]` / `"r,g,b"`); and
- **pages**: each screen binds its ROLES -> palette name(s) and owns a background GRADIENT.

A role resolves to the palette entry of the SAME name unless the page remaps it (identity
default), so the built-in look is uniform and per-page divergence is opt-in. A role mapped to a
LIST of names zebra-stripes rows by index. Every page gets a distinct default gradient.

Preference order per color: (1) true 24-bit via `curses.init_color` when the terminal can change
colors; (2) the xterm-256 cube approximation; (3) the basic 8. The diagonal background GRADIENT
is only painted under true 24-bit (the cube crushes dark purples into a few bright blocks).

Colors are user-overridable: a `theme:` section in the config (see Config.theme / resolve_theme)
supplies `palette:` entries and `pages:` bindings/gradients.
'''

import curses

# Raw semantic RGB (0-255) — the source the built-in palette is built from, and a friendly set of
# names to reference. A `palette.<name>` override replaces or extends any of these.
_SEM = {
    'header': (120, 200, 255), 'title': (235, 235, 235),
    'installed': (90, 200, 120), 'outdated': (230, 190, 70), 'partial': (90, 190, 205),
    'missing': (150, 150, 150), 'locked': (110, 165, 255), 'unsupported': (110, 110, 110),
    'untrusted': (220, 140, 60), 'error': (235, 95, 95),
    'op_install': (90, 200, 120), 'op_upgrade': (230, 190, 70), 'op_remove': (235, 95, 95),
    'op_lock': (110, 165, 255), 'op_unlock': (120, 210, 210),
    'dim': (120, 120, 120), 'accent': (200, 140, 240),
}
SEMANTIC = _SEM             # back-compat alias

GRAD_MAX_BANDS = 96         # cap on the (range-adaptive) number of diagonal gradient steps


def _s(fg, bg=None, bold=False, underline=False, reverse=False):
    '''Build a built-in palette style; `fg`/`bg` may name a _SEM color or be an rgb tuple.'''
    st = {'fg': _SEM.get(fg, fg) if isinstance(fg, str) else fg}
    if bg is not None:
        st['bg'] = _SEM.get(bg, bg) if isinstance(bg, str) else bg
    if bold:
        st['bold'] = True
    if underline:
        st['underline'] = True
    if reverse:
        st['reverse'] = True
    return st


# The built-in palette: every raw color as an fg-only style, plus the composite element styles
# that make up the default look. Role names match what the renderer asks for (identity binding).
BUILTIN_PALETTE = {
    **{name: {'fg': rgb} for name, rgb in _SEM.items()},
    'label':          _s('title', bg='accent', bold=True),   # the `configsys` chip
    'os':             _s('header', bold=True),
    'issue_error':    _s('error', bold=True, reverse=True),
    'issue_warning':  _s('outdated', bold=True, reverse=True),
    'menu_header':    _s('dim', bold=True),
    'select_marker':  _s('accent', bold=True),
    'profile':        _s('accent', bold=True),
    'link':           _s('accent', bold=True),
    'component':      _s('title', bold=True),
    'unit':           _s('title'),
    'driver':         _s('dim'),
    'scope':          _s('dim'),
    'scope_choice':   _s('accent'),
    'version':        _s('dim'),
    'row_error':      _s('error'),
    'methods':        _s('header'),
    'info':           _s('accent'),
    'info_dim':       _s('dim'),
    'status_line':    _s('accent'),
    'footer':         _s('dim', reverse=True),
    'op_install':     _s('op_install', bold=True), 'op_upgrade': _s('op_upgrade', bold=True),
    'op_remove':      _s('op_remove', bold=True),  'op_lock':    _s('op_lock', bold=True),
    'op_unlock':      _s('op_unlock', bold=True),  'op_mixed':   _s('accent', bold=True),
}

# The five content screens (the Theme editor previews all of them); 'theme' is the editor's own.
DEMO_PAGES = ['components', 'profiles', 'plugins', 'dotfiles', 'config']
ALL_PAGES = DEMO_PAGES + ['theme']

# Each page's default background gradient (from top-left, to bottom-right, selected-row bar) — a
# distinct dark hue per page, for the whims. Overridable via `pages.<page>.gradient`.
BUILTIN_GRADIENTS = {
    'components': ((22, 10, 34), (5, 2, 10), (58, 34, 88)),    # purple
    'profiles':   ((8, 34, 28), (2, 9, 6), (28, 74, 62)),      # teal
    'plugins':    ((10, 22, 40), (2, 5, 12), (34, 62, 108)),   # blue
    'dotfiles':   ((36, 24, 8), (9, 6, 2), (78, 58, 28)),      # amber
    'config':     ((20, 20, 42), (5, 5, 16), (44, 44, 88)),    # indigo/slate
    'theme':      ((38, 10, 26), (10, 2, 6), (86, 34, 58)),    # rose
}


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _flag(v):
    '''A style boolean. humon materializes `true`/`false` as strings, so treat 'false'/'no'/'0'
    as off (a bare `if v` would count the string 'false' as true).'''
    if isinstance(v, str):
        return v.strip().lower() in ('true', 'yes', 'on', '1')
    return bool(v)


def parse_color(v):
    '''An (r,g,b) 0-255 tuple from a hex string ("#rrggbb"/"#rgb"), an [r,g,b] list, or an
    "r,g,b" string; None if unparseable.'''
    if isinstance(v, (list, tuple)) and len(v) == 3:
        try:
            return tuple(max(0, min(255, int(c))) for c in v)
        except (TypeError, ValueError):
            return None
    if not isinstance(v, str):
        return None
    s = v.strip()
    if s.startswith('#'):
        h = s[1:]
        if len(h) == 3:
            h = ''.join(c * 2 for c in h)
        if len(h) == 6:
            try:
                return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                return None
        return None
    if ',' in s:
        try:
            parts = [int(p) for p in s.split(',')]
        except ValueError:
            return None
        return tuple(max(0, min(255, c)) for c in parts) if len(parts) == 3 else None
    return None


def _resolve_style(st):
    '''Coerce a palette style dict's fg/bg to rgb tuples (dropping an unparseable bg), leaving the
    effect flags. Returns a normalized {fg:(r,g,b), bg:(r,g,b)?, bold?, underline?, reverse?}.'''
    out = {}
    fg = st.get('fg')
    out['fg'] = fg if isinstance(fg, tuple) else (parse_color(fg) or _SEM['title'])
    if st.get('bg') is not None:
        bg = st['bg'] if isinstance(st['bg'], tuple) else parse_color(st['bg'])
        if bg:
            out['bg'] = bg
    for fl in ('bold', 'underline', 'reverse'):
        if st.get(fl):
            out[fl] = True
    return out


def resolve_theme(theme):
    '''Merge a `theme:` override dict (already layer-merged by Config.theme — {palette, pages,
    splash}) onto the built-ins. Pure — no curses. Returns (palette, pages):

    - palette: {name: normalized-style} (fg/bg rgb tuples + effect flags);
    - pages:   {page: {'roles': {role: name | [names]}, 'grad': (from, to, sel, enabled)}}.
    '''
    theme = theme if isinstance(theme, dict) else {}
    palette = {name: dict(st) for name, st in BUILTIN_PALETTE.items()}
    for name, ov in (theme.get('palette') or {}).items():
        base = palette.get(name, {})
        if isinstance(ov, dict):
            for k in ('fg', 'bg', 'bold', 'underline', 'reverse'):
                if k not in ov:
                    continue
                if k == 'bg' and ov[k] in (None, 'none', '', 'false', False):
                    base.pop('bg', None)
                elif k in ('bold', 'underline', 'reverse'):
                    base[k] = _flag(ov[k])
                    if not base[k]:
                        base.pop(k)
                else:
                    base[k] = ov[k]
        else:                                        # bare color shorthand -> fg
            base = dict(base, fg=ov)
        palette[name] = base
    palette = {name: _resolve_style(st) for name, st in palette.items()}

    upages = theme.get('pages') or {}
    pages = {}
    for page in ALL_PAGES:
        spec = upages.get(page) if isinstance(upages.get(page), dict) else {}
        roles = dict(spec.get('roles') or {})
        ga, gb, gs = BUILTIN_GRADIENTS.get(page, BUILTIN_GRADIENTS['components'])
        enabled = True
        g = spec.get('gradient')
        if isinstance(g, dict):
            if g.get('enabled') in (False, 'false', 'no', 'off'):
                enabled = False
            ga = parse_color(g.get('from')) or ga
            gb = parse_color(g.get('to')) or gb
            gs = parse_color(g.get('selected')) or gs
        elif g in (False, 'false', 'no', 'off'):
            enabled = False
        pages[page] = {'roles': roles, 'grad': (ga, gb, gs, enabled)}
    return palette, pages


def rgb_to_256(r, g, b):
    if r == g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return 232 + round((r - 8) / 247 * 24)
    return (16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5))


def rgb_to_basic8(r, g, b):
    bright = (r + g + b) / 3
    if bright < 40:
        return curses.COLOR_BLACK
    if bright > 210 and abs(r - g) < 40 and abs(g - b) < 40:
        return curses.COLOR_WHITE
    if r >= g and r >= b:
        return curses.COLOR_YELLOW if g > 120 else curses.COLOR_RED
    if g >= r and g >= b:
        return curses.COLOR_GREEN if b < 150 else curses.COLOR_CYAN
    return curses.COLOR_BLUE if r < 150 else curses.COLOR_MAGENTA


class Palette:
    '''Resolves the theme to curses attrs. Holds every page's resolved roles + gradient; the active
    page is selected with `use_page` (call sites stay `pal.style('component', ...)`). Color slots
    and pairs are deduped across all pages, so switching pages is free and never overflows.'''
    def __init__(self, theme=None):
        curses.start_color()
        self.bg = -1
        try:
            curses.use_default_colors()
        except curses.error:
            self.bg = curses.COLOR_BLACK
        self.have256 = curses.COLORS >= 256
        self.direct = curses.COLORS >= (1 << 24)
        try:
            self.truecolor = self.direct or (self.have256 and curses.can_change_color())
        except curses.error:
            self.truecolor = self.direct

        palette, pages = resolve_theme(theme)
        self._next_color = 16          # private palette-slot allocator (truecolor mode)
        self._next_pair = 1
        self._color_cache = {}         # rgb -> palette index
        self._pair_cache = {}          # (fg_idx, bg_idx) -> attr

        # resolve each palette entry to (fg_idx, bg_idx-or-None, attr-flags)
        self._pal = {}
        self._fg = {}                  # name -> fg palette index (at()/get()/fallback)
        for name, st in palette.items():
            fg = self._color(st['fg'])
            bg = self._color(st['bg']) if st.get('bg') else None
            flags = ((curses.A_BOLD if st.get('bold') else 0)
                     | (curses.A_UNDERLINE if st.get('underline') else 0)
                     | (curses.A_REVERSE if st.get('reverse') else 0))
            self._pal[name] = (fg, bg, flags)
            self._fg[name] = fg

        # per-page gradient bands + role bindings
        self._pages = {}
        for page, pg in pages.items():
            ga, gb, gs, enabled = pg['grad']
            on = self.truecolor and enabled
            grad_bg, sel_bg = [], None
            if on:
                span = max(abs(ga[i] - gb[i]) for i in range(3))
                n = max(16, min(GRAD_MAX_BANDS, span + 1))
                grad_bg = [self._color(_lerp(ga, gb, k / (n - 1))) for k in range(n)]
                sel_bg = self._color(gs)
            self._pages[page] = {'roles': pg['roles'], 'grad_bg': grad_bg, 'sel_bg': sel_bg, 'on': on}
        self.page_name = None
        self.use_page('components')

    # -- page selection --------------------------------------------------

    def use_page(self, page):
        '''Make `page` the active page — its role bindings + gradient drive subsequent draws.'''
        pg = self._pages.get(page) or self._pages['components']
        self._roles = pg['roles']
        self._grad_bg = pg['grad_bg']
        self._sel_bg = pg['sel_bg']
        self.gradient = pg['on']
        self.page_name = page

    def _entry(self, role, row=0):
        '''(fg_idx, bg_idx|None, flags) for a role on the active page: the page's binding for
        `role` (a palette name, or a list zebra-indexed by `row`), else the same-named palette
        entry (identity), else a dim fallback.'''
        name = self._roles.get(role, role)
        if isinstance(name, list):
            name = name[row % len(name)] if name else role
        return self._pal.get(name) or self._pal.get(role) or (self._fg.get('dim', 0), None, 0)

    # -- color/pair allocation ------------------------------------------

    def _color(self, rgb):
        key = tuple(rgb)
        if key in self._color_cache:
            return self._color_cache[key]
        r, g, b = rgb
        idx = None
        if self.direct:                                    # color number IS the packed 24-bit RGB
            idx = (r << 16) | (g << 8) | b
        elif self.truecolor and self._next_color < curses.COLORS:
            idx = self._next_color
            try:
                curses.init_color(idx, round(r / 255 * 1000), round(g / 255 * 1000),
                                  round(b / 255 * 1000))
                self._next_color += 1
            except curses.error:
                idx = None
        if idx is None:
            idx = rgb_to_256(*rgb) if self.have256 else rgb_to_basic8(*rgb)
        self._color_cache[key] = idx
        return idx

    def _pair(self, fg_idx, bg_idx):
        attr = self._pair_cache.get((fg_idx, bg_idx))
        if attr is None:
            n = self._next_pair
            try:
                curses.init_pair(n, fg_idx, bg_idx)
                attr = curses.color_pair(n)
                self._next_pair += 1
            except curses.error:
                attr = curses.A_NORMAL
            self._pair_cache[(fg_idx, bg_idx)] = attr
        return attr

    def get(self, name):
        fg = self._fg.get(name)
        return self._pair(fg, self.bg) if fg is not None else curses.A_NORMAL

    def rgb_attr(self, rgb):
        '''An attr painting `rgb` as fg over the default background — for ad-hoc colors (the splash)
        outside the semantic map. Shares the slot/pair allocator + caches and degrades gracefully.'''
        return self._pair(self._color(rgb), self.bg)

    def rgb_pair(self, fg_rgb, bg_rgb):
        '''Like rgb_attr but over an explicit bg colour (a splash glyph over the liquid colour).'''
        return self._pair(self._color(fg_rgb), self._color(bg_rgb))

    # -- gradient-aware drawing (active page) ---------------------------

    def band(self, y, x, h, w):
        '''The gradient band index for a cell, along the top-left -> bottom-right diagonal.'''
        n = len(self._grad_bg)
        t = (y / max(1, h - 1) + x / max(1, w - 1)) / 2
        return min(n - 1, int(t * n))

    def style(self, element, y, x, h, w, *, selected=False, row=0):
        '''The attr for a role at cell (y, x): its fg + flags, over its own bg if the palette entry
        declares one, else the active page's diagonal gradient (or the selected-row bar). `row`
        zebra-indexes a list-valued role binding.'''
        fg, elem_bg, flags = self._entry(element, row)
        if not self.gradient:
            base = self._pair(fg, elem_bg if elem_bg is not None else self.bg)
            return base | flags | (curses.A_REVERSE if selected else 0)
        bg = self._sel_bg if selected else (elem_bg if elem_bg is not None
                                            else self._grad_bg[self.band(y, x, h, w)])
        return self._pair(fg, bg) | flags

    def at(self, name, y, x, h, w, *, selected=False, row=0):
        '''`name`'s fg over the gradient background (or the selected bar) — flags/bg ignored, for
        the many by-name row colorings (status column, etc).'''
        fg = self._entry(name, row)[0]
        if not self.gradient:
            return self._pair(fg, self.bg) | (curses.A_REVERSE if selected else 0)
        bg = self._sel_bg if selected else self._grad_bg[self.band(y, x, h, w)]
        return self._pair(fg, bg)

    def fill(self, y, x, h, w, *, selected=False):
        '''A blank-cell background attr (fg == bg) for painting the empty canvas behind text.'''
        if not self.gradient:
            return curses.A_REVERSE if selected else curses.A_NORMAL
        bg = self._sel_bg if selected else self._grad_bg[self.band(y, x, h, w)]
        return self._pair(bg, bg)


# Which palette role to paint each component status.
STATUS_COLOR = {
    'installed': 'installed', 'outdated': 'outdated', 'partial': 'partial', 'missing': 'missing',
    'locked': 'locked', 'unsupported': 'unsupported', 'untrusted': 'untrusted', 'error': 'error',
}
