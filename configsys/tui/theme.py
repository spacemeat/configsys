'''theme.py — color for the TUI, 24-bit when the terminal allows it.

The model is two tiers (see docs/theme-redesign.md):

- a shared **color map** — a name -> #rrggbb dict (`theme.colors`); and
- **pages** — each screen's ROLES carry a style `{ fg, bg, bold, underline, reverse }` where fg/bg
  are a color-map NAME or a literal color; plus that page's background **gradient**.

A role's style defaults to a built-in (uniform across pages); a page overrides just what differs,
so per-page divergence is opt-in. fg/bg resolve against the shared map, so retinting one map color
re-tints every role that references it. Every page gets a distinct default gradient.

Rendering: true 24-bit via `curses.init_color` when the terminal can change colors (or a
direct-color terminal where the color number IS the packed RGB); otherwise the xterm-256 cube, or
the basic 8. The diagonal background GRADIENT is only painted under true 24-bit. `Palette.color_mode`
names what the terminal actually gave us (shown on the Theme screen).
'''

import curses

# The shared color MAP: a name -> rgb (0-255). `theme.colors.<name>` overrides one or adds a new
# name; roles reference these by name (or use a literal color).
COLOR_MAP = {
    'header': (120, 200, 255), 'title': (235, 235, 235), 'accent': (200, 140, 240),
    'dim': (120, 120, 120), 'ink': (220, 220, 220), 'ink_dim': (154, 154, 154),
    'installed': (90, 200, 120), 'outdated': (230, 190, 70), 'partial': (90, 190, 205),
    'missing': (150, 150, 150), 'locked': (110, 165, 255), 'unsupported': (110, 110, 110),
    'untrusted': (220, 140, 60), 'error': (235, 95, 95),
    'op_install': (90, 200, 120), 'op_upgrade': (230, 190, 70), 'op_remove': (235, 95, 95),
    'op_lock': (110, 165, 255), 'op_unlock': (120, 210, 210),
    'sel_bg': (58, 34, 88),
    'row_desc': (108, 112, 128),                         # faded inline component descriptions
    'method_dim': (124, 150, 176),                       # muted slate-blue for the method label
    'dep_dim': (192, 158, 108),                          # muted amber for the "required by" line
}

# --- low-color (8/16) hand-tuning ---------------------------------------------------------------
# Quantizing the 24-bit map into 8 ANSI hues loses too much (greys collapse, everything muddies).
# BASIC_MAP pins each built-in color NAME to an explicit ANSI slot for the 8/16-color path — the ONLY
# way to reach the bright set (8..15), which is where the legible low-color look lives. A user's
# `theme.colors-basic` (same name -> slot) overrides/extends this. In 256/truecolor mode it's unused.
ANSI8 = ['black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white']

BASIC_MAP = {
    'header': 'bright-blue', 'title': 'bright-white', 'accent': 'bright-magenta',
    'dim': 'bright-black', 'ink': 'white', 'ink_dim': 'bright-black',
    'installed': 'bright-green', 'outdated': 'bright-yellow', 'partial': 'bright-cyan',
    'missing': 'bright-black', 'locked': 'blue', 'unsupported': 'bright-black',
    'untrusted': 'yellow', 'error': 'bright-red',
    'op_install': 'bright-green', 'op_upgrade': 'bright-yellow', 'op_remove': 'bright-red',
    'op_lock': 'blue', 'op_unlock': 'cyan',
    'sel_bg': 'magenta',                                 # the selection-bar background in 8/16-color
    'row_desc': 'bright-black', 'method_dim': 'bright-black', 'dep_dim': 'yellow',
}


def parse_ansi(val):
    '''An ANSI color slot for the low-color path: one of the 8 names (black red green yellow blue
    magenta cyan white), a `bright-<name>` (slots 8..15), `grey`/`gray` (= bright-black), a bare int
    0..15, or `default`/`term` (-1, the terminal's own default). Returns the index, -1, or None.'''
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val if -1 <= val <= 15 else None
    s = str(val).strip().lower().replace('_', '-')
    if s in ('default', 'term', 'terminal', '-1'):
        return -1
    if s.lstrip('-').isdigit():
        n = int(s)
        return n if 0 <= n <= 15 else None
    bright = False
    if s.startswith('bright-'):
        bright, s = True, s[7:]
    elif s.endswith('-bright'):
        bright, s = True, s[:-7]
    if s in ('grey', 'gray'):
        return 15 if bright else 8                       # grey == bright-black; bright-grey -> white
    if s in ANSI8:
        return ANSI8.index(s) + (8 if bright else 0)
    return None


def ansi_name(idx):
    '''The canonical name for an ANSI slot (inverse of parse_ansi) — for a readable full_snapshot.'''
    if idx == -1:
        return 'default'
    if 0 <= idx <= 7:
        return ANSI8[idx]
    if 8 <= idx <= 15:
        return 'bright-' + ANSI8[idx - 8]
    return str(idx)


def resolve_basic(theme, colors):
    '''The low-color (8/16) override as {rgb: ansi_index}: the built-in BASIC_MAP overlaid by
    `theme.colors-basic` (both name -> ANSI slot), keyed by each name's RESOLVED rgb (from `colors`)
    so the Palette can consult it before quantizing — one entry then covers every role that
    references that map color. Names absent from the map or with an unparseable slot are skipped.
    User entries are applied last, so they win even where two names share an rgb.'''
    theme = theme if isinstance(theme, dict) else {}
    out = {}

    def apply(items):
        for name, val in items:
            rgb, idx = colors.get(name), parse_ansi(val)
            if rgb is not None and idx is not None:
                out[tuple(rgb)] = idx

    apply(BASIC_MAP.items())
    ub = theme.get('colors-basic')
    if isinstance(ub, dict):
        apply(ub.items())
    return out


GRAD_MAX_BANDS = 96         # cap on the (range-adaptive) number of diagonal gradient steps


def _r(fg, bg=None, bold=False, underline=False, reverse=False):
    '''A built-in role style; fg/bg are color-map NAMES (resolved against COLOR_MAP at use).'''
    st = {'fg': fg}
    if bg:
        st['bg'] = bg
    if bold:
        st['bold'] = True
    if underline:
        st['underline'] = True
    if reverse:
        st['reverse'] = True
    return st


# Built-in role styles — the default look, uniform across pages. Each page overrides only what it
# wants to differ. fg/bg are map names; `selection` is the cursor row (its bg is the selected bar).
ROLE_DEFAULTS = {
    'label': _r('title', bg='accent', bold=True),        # the `configsys` chip
    'os': _r('header', bold=True),
    'issue_error': _r('error', bold=True, reverse=True),
    'issue_warning': _r('outdated', bold=True, reverse=True),
    'menu_header': _r('dim', bold=True),
    'select_marker': _r('accent', bold=True),
    'profile': _r('accent', bold=True),
    'link': _r('accent', bold=True),
    'component': _r('title', bold=True),
    'unit': _r('title'),
    'driver': _r('dim'),
    'scope': _r('dim'),
    'scope_choice': _r('accent'),
    'version': _r('dim'),
    'row_error': _r('error'),
    'methods': _r('header'),
    'method_dim': _r('method_dim'),                      # muted method label (Profiles detail pane)
    'dependents': _r('dep_dim'),                         # "required by" reverse-deps (Profiles detail)
    'row_desc': _r('row_desc'),                          # faded description trailing the row name
    'info': _r('accent'),
    'info_dim': _r('dim'),
    'status_line': _r('accent'),
    'footer': _r('dim', reverse=True),
    'selection': _r('title', bg='sel_bg', bold=True),
    'installed': _r('installed'), 'outdated': _r('outdated'), 'partial': _r('partial'),
    'missing': _r('missing'), 'locked': _r('locked'), 'unsupported': _r('unsupported'),
    'untrusted': _r('untrusted'), 'error': _r('error'),
    'op_install': _r('op_install', bold=True), 'op_upgrade': _r('op_upgrade', bold=True),
    'op_remove': _r('op_remove', bold=True), 'op_lock': _r('op_lock', bold=True),
    'op_unlock': _r('op_unlock', bold=True), 'op_mixed': _r('accent', bold=True),
    # Plugins diff pane: added/removed lines and the hunk/meta gutter (git-diff green/red).
    'diff_add': _r('installed'), 'diff_del': _r('error'),
    'diff_hunk': _r('partial', bold=True), 'diff_meta': _r('dim'),
    # raw passthrough roles for direct at()/get() references (identity -> the same-named map color)
    'accent': _r('accent'), 'dim': _r('dim'), 'title': _r('title'), 'header': _r('header'),
}

# Roles surfaced in the editor's per-page list (the passthrough ones above are internal).
EDITABLE_ROLES = [r for r in ROLE_DEFAULTS if r not in ('accent', 'dim', 'title', 'header')]

# The five content screens (the Theme editor previews all of them); 'theme' is the editor's own.
DEMO_PAGES = ['components', 'profiles', 'plugins', 'dotfiles', 'config']
ALL_PAGES = DEMO_PAGES + ['theme']

# The roles each SCREEN actually uses — drives both the editor's per-page list (list 2) and its
# sample mock, so they swap as you cycle pages and show only what that page needs.
PAGE_ROLES = {
    'components': ['label', 'os', 'issue_warning', 'menu_header', 'component', 'unit', 'driver',
                   'version', 'scope', 'scope_choice', 'installed', 'outdated', 'partial', 'missing',
                   'locked', 'op_install', 'op_upgrade', 'op_remove', 'op_lock', 'row_error',
                   'row_desc', 'methods', 'info', 'info_dim', 'status_line', 'footer', 'selection'],
    'profiles':  ['label', 'os', 'menu_header', 'profile', 'link', 'component', 'info', 'info_dim',
                  'dependents', 'method_dim', 'status_line', 'footer', 'selection'],
    'plugins':   ['label', 'os', 'menu_header', 'component', 'unit', 'installed', 'outdated',
                  'missing', 'untrusted', 'accent', 'diff_add', 'diff_del', 'diff_hunk', 'diff_meta',
                  'info', 'info_dim', 'status_line', 'footer', 'selection'],
    'dotfiles':  ['label', 'os', 'menu_header', 'component', 'unit', 'installed', 'outdated',
                  'missing', 'info_dim', 'status_line', 'footer', 'selection'],
    'config':    ['label', 'os', 'menu_header', 'component', 'scope', 'scope_choice', 'info_dim',
                  'status_line', 'footer', 'selection'],
    'theme':     ['label', 'menu_header', 'info_dim', 'component', 'status_line', 'footer', 'selection'],
}

# Each page's default background gradient (top-left -> bottom-right) — a distinct dark hue per page,
# for the whims. Kept genuinely dark (brightest corner stays low) so text always reads over it.
BUILTIN_GRADIENTS = {
    'components': ((20, 10, 30), (5, 2, 10)),      # purple
    'profiles':   ((7, 24, 20), (2, 8, 6)),        # teal
    'plugins':    ((8, 18, 34), (2, 5, 12)),       # blue
    'dotfiles':   ((28, 20, 8), (8, 6, 2)),        # amber
    'config':     ((16, 17, 34), (4, 4, 12)),      # indigo/slate
    'theme':      ((32, 11, 24), (9, 3, 7)),       # rose
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


def _ref_rgb(ref, colors):
    '''Resolve a role fg/bg reference: a color-map NAME -> its rgb, else a literal color value.'''
    if isinstance(ref, str) and ref in colors:
        return colors[ref]
    return parse_color(ref)


def resolve_theme(theme):
    '''Merge a `theme:` override dict (already layer-merged by Config.theme — {colors, pages,
    splash}) onto the built-ins. Pure — no curses. Returns (colors, pages):

    - colors: {name: (r,g,b)} — the resolved shared map;
    - pages:  {page: {'roles': {role: {fg:(r,g,b), bg:(r,g,b)|None, bold, underline, reverse}},
               'grad': (from, to, enabled), 'sel_bg': (r,g,b)|None}}.
    '''
    theme = theme if isinstance(theme, dict) else {}
    colors = dict(COLOR_MAP)
    for name, val in (theme.get('colors') or {}).items():
        rgb = parse_color(val)
        if rgb:
            colors[name] = rgb

    upages = theme.get('pages') or {}
    pages = {}
    for page in ALL_PAGES:
        spec = upages.get(page) if isinstance(upages.get(page), dict) else {}
        roles = {}
        for role, dfl in ROLE_DEFAULTS.items():
            st = dict(dfl)
            ov = spec.get(role)
            if isinstance(ov, dict):
                st.update(ov)                         # per-page fg/bg/effect override
            fg = _ref_rgb(st.get('fg'), colors) or (235, 235, 235)
            bgref = st.get('bg')
            bg = _ref_rgb(bgref, colors) if bgref not in (None, '', 'none', 'false', False) else None
            if bg == fg:                              # never paint text invisibly on its own color
                bg = None
            roles[role] = {'fg': fg, 'bg': bg, 'bold': _flag(st.get('bold')),
                           'underline': _flag(st.get('underline')), 'reverse': _flag(st.get('reverse'))}
        ga, gb = BUILTIN_GRADIENTS.get(page, BUILTIN_GRADIENTS['components'])
        enabled = True
        g = spec.get('gradient')
        if isinstance(g, dict):
            if g.get('enabled') in (False, 'false', 'no', 'off'):
                enabled = False
            ga = _ref_rgb(g.get('from'), colors) or ga   # endpoints may name a map color or literal
            gb = _ref_rgb(g.get('to'), colors) or gb
        elif g in (False, 'false', 'no', 'off'):
            enabled = False
        pages[page] = {'roles': roles, 'grad': (ga, gb, enabled), 'sel_bg': roles['selection']['bg']}
    return colors, pages


def full_snapshot(theme):
    '''The COMPLETE current theme as a self-contained two-tier dict — every color-map entry
    (name -> #rrggbb) and, per content page, EVERY role that page uses (fg/bg refs + effects) plus
    the gradient endpoints — resolved from the built-in defaults overlaid by `theme`. Unlike the
    diff overrides (theme_overrides), this pins the whole look so a saved pack reproduces exactly
    even if built-in defaults later change. fg/bg stay as refs (map names or literals) so the map is
    still the single place to retint; the full map is saved alongside, so the refs always resolve.'''
    colors, pages = resolve_theme(theme)
    upages = (theme.get('pages') if isinstance(theme, dict) else None) or {}
    out_pages = {}
    for page in DEMO_PAGES:
        spec = upages.get(page) if isinstance(upages.get(page), dict) else {}
        pg = {}
        for role in PAGE_ROLES.get(page, []):
            st = dict(ROLE_DEFAULTS.get(role, {}))
            ov = spec.get(role)
            if isinstance(ov, dict):
                st.update(ov)
            entry = {'fg': st.get('fg', 'title')}
            if st.get('bg') not in (None, '', 'none', 'false', False):
                entry['bg'] = st['bg']
            for fl in ('bold', 'underline', 'reverse'):
                if _flag(st.get(fl)):
                    entry[fl] = True
            pg[role] = entry
        g = spec.get('gradient') if isinstance(spec.get('gradient'), dict) else {}
        ga, gb = BUILTIN_GRADIENTS.get(page, BUILTIN_GRADIENTS['components'])
        grad = {'from': g.get('from') or '#%02x%02x%02x' % ga,
                'to': g.get('to') or '#%02x%02x%02x' % gb}
        if not pages[page]['grad'][2]:
            grad['enabled'] = False
        pg['gradient'] = grad
        out_pages[page] = pg
    basic = dict(BASIC_MAP)                               # the full low-color map, spelled out
    ub = theme.get('colors-basic') if isinstance(theme, dict) else None
    if isinstance(ub, dict):
        for name, val in ub.items():
            idx = parse_ansi(val)
            if idx is not None:
                basic[name] = ansi_name(idx)             # normalize the override to a canonical name
    return {'colors': {name: '#%02x%02x%02x' % rgb for name, rgb in colors.items()},
            'colors-basic': basic, 'pages': out_pages}


def rgb_to_256(r, g, b):
    if r == g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return 232 + round((r - 8) / 247 * 24)
    return (16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5))


def rgb_to_basic8(r, g, b):
    '''Nearest of the 8 ANSI colors. Low-saturation colors are GREY (which the 8-color set lacks), so
    map those to black/white by brightness rather than forcing a hue — the old hue-first version sent
    mid-greys to yellow and leaned red. Saturated colors bucket into the 6 hues: a channel counts as
    "on" at >=60% of the brightest, and R + 2·G + 4·B is exactly the ANSI color order (black=0 … white=7).'''
    mx, mn = max(r, g, b), min(r, g, b)
    if mx - mn < 40:                                   # near-grey: no grey in the 8-color set
        return curses.COLOR_BLACK if mx < 100 else curses.COLOR_WHITE
    t = mx * 0.6
    return (1 if r >= t else 0) + 2 * (1 if g >= t else 0) + 4 * (1 if b >= t else 0)


def env_color_cap(env=None):
    '''Resolve a color-depth CAP from the environment — it only clamps the detected mode DOWN, never
    up (you can't fake 24-bit on an 8-color tty). `NO_COLOR` (any non-empty value, per no-color.org)
    forces monochrome; `CONFIGSYS_COLOR` is the explicit override the --color/--nocolor flags set.
    Returns one of 'none'|'basic8'|'basic16'|'256'|'truecolor', or None for auto-detect. `basic8`
    forces the base 8 (no bright slots); `basic16` allows the bright ANSI colors 8..15.'''
    import os
    env = os.environ if env is None else env
    if (env.get('NO_COLOR') or '').strip():
        return 'none'
    v = (env.get('CONFIGSYS_COLOR') or '').strip().lower()
    if v in ('none', 'no', 'off', '0', 'mono', 'nocolor'):
        return 'none'
    if v in ('8', '8color'):
        return 'basic8'
    if v in ('16', 'basic', 'ansi', '16color'):
        return 'basic16'
    if v in ('256', '256color', '8bit'):
        return '256'
    if v in ('24bit', '24', 'truecolor', 'direct', 'rgb'):
        return 'truecolor'
    return None                                        # 'auto', '', or unrecognized -> auto-detect


def env_effects(env=None):
    '''The resolved TUI motion level from the environment ('full'|'reduced'|'none'), or None. The TUI
    canonicalizes CONFIGSYS_EFFECTS (from --effects / the `effects:` setting / an SSH auto-default)
    into this before building the Palette, so the gradient + splash read one value.'''
    import os
    env = os.environ if env is None else env
    v = (env.get('CONFIGSYS_EFFECTS') or '').strip().lower()
    return v if v in ('full', 'reduced', 'none') else None


class Palette:
    '''Resolves the theme to curses attrs. Holds every page's resolved role styles + gradient; the
    active page is selected with `use_page` (call sites stay `pal.style('component', ...)`). Color
    slots and pairs are deduped across all pages, so switching pages is free.'''
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

        # CLAMP the detected mode down per --color/--nocolor/NO_COLOR (never up). `none` = monochrome:
        # no color pairs at all, only structural A_REVERSE/A_BOLD survive (see the render methods).
        cap = env_color_cap()
        self.mono = cap == 'none'
        if cap in ('256', 'basic8', 'basic16', 'none'):
            self.truecolor = self.direct = False
        if cap in ('basic8', 'basic16', 'none'):
            self.have256 = False
        # The bright ANSI slots (8..15) — where the legible low-color look lives — exist only at
        # COLORS>=16; `--color 8` forces the base 8 to preview the true fallback.
        self.have16 = curses.COLORS >= 16 and cap != 'basic8'
        # the 8/16-color path (where quantization can collide fg with bg) -> the contrast guard runs.
        self.lowcolor = not (self.have256 or self.truecolor or self.direct or self.mono)
        # motion: reduced/none disable the diagonal gradient (the per-cell repaint that's costly over
        # a thin SSH link); `full` (or unset) keeps it. The splash is gated separately, at the TUI.
        self.grad_ok = env_effects() in (None, 'full')

        colors, pages = resolve_theme(theme)
        self._basic = resolve_basic(theme, colors)   # {rgb: ansi_slot} hand-tuning for the 8/16 path
        self._next_color = 16          # private palette-slot allocator (truecolor mode)
        self._next_pair = 1
        self._color_cache = {}         # rgb -> palette index
        self._pair_cache = {}          # (fg_idx, bg_idx) -> attr
        self._map = {name: self._color(rgb) for name, rgb in colors.items()}   # for at()/get()

        self._pages = {}
        for page, pg in pages.items():
            roles = {}
            for role, st in pg['roles'].items():
                flags = ((curses.A_BOLD if st['bold'] else 0)
                         | (curses.A_UNDERLINE if st['underline'] else 0)
                         | (curses.A_REVERSE if st['reverse'] else 0))
                bg = self._color(st['bg']) if st['bg'] is not None else None
                roles[role] = (self._color(st['fg']), bg, flags)
            ga, gb, enabled = pg['grad']
            on = self.truecolor and enabled and self.grad_ok
            grad_bg = []
            if on:
                span = max(abs(ga[i] - gb[i]) for i in range(3))
                n = max(16, min(GRAD_MAX_BANDS, span + 1))
                grad_bg = [self._color(_lerp(ga, gb, k / (n - 1))) for k in range(n)]
            sel_bg_rgb = pg['sel_bg']
            sel_bg = self._color(sel_bg_rgb) if sel_bg_rgb is not None else self.bg
            self._pages[page] = {'roles': roles, 'grad_bg': grad_bg, 'sel_bg': sel_bg,
                                 'sel_bg_rgb': tuple(sel_bg_rgb) if sel_bg_rgb is not None else (0, 0, 0),
                                 'on': on}
        self.page_name = None
        self.use_page('components')

    @property
    def color_mode(self):
        if self.mono:
            return 'none (monochrome)'
        if self.direct:
            return 'direct 24-bit'
        if self.truecolor:
            return '24-bit'
        if self.have256:
            return '256-color (approx)'
        return '16-color' if self.have16 else '8-color'

    def new_frame(self):
        '''Reset the color-PAIR allocator at the start of each full redraw. `curses.color_pair()`
        encodes the pair number in only 8 bits (A_COLOR == 0xff00), so pair numbers MUST stay < 256
        or they wrap to a different pair's colors. One Palette is shared for the whole session and
        pairs never free, so without this a long session (or the pair-heavy Theme screen) eventually
        exceeds 255 and every over-256 cell renders in the wrong color. Color SLOTS persist (they're
        bounded by the theme's distinct colors, < 256); only pairs — the fg×bg combinations, of
        which there are far more — are recycled each frame, which curses is built to handle.'''
        self._next_pair = 1
        self._pair_cache.clear()

    def use_page(self, page):
        pg = self._pages.get(page) or self._pages['components']
        self._roles = pg['roles']
        self._grad_bg = pg['grad_bg']
        self._sel_bg = pg['sel_bg']
        self._sel_bg_rgb = pg['sel_bg_rgb']
        self.gradient = pg['on']
        self.page_name = page

    @property
    def sel_bg_rgb(self):
        '''The active page's selection-bar rgb — so callers can derive dimmer/subtler row tints
        (e.g. a residual selection or a member highlight) that stay in the theme's family.'''
        return self._sel_bg_rgb

    def _entry(self, role):
        r = self._roles.get(role)
        if r is not None:
            return r
        idx = self._map.get(role, self._map.get('dim', 0))   # a color-map name used as a role
        return (idx, None, 0)

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
            if self.have256:
                idx = rgb_to_256(*rgb)
            else:                                          # 8/16-color: an explicit hand-tuned slot
                idx = self._basic.get(key)                 # wins over the automatic quantizer
                if idx is None:
                    idx = rgb_to_basic8(*rgb)
                elif idx >= 8 and not self.have16:
                    idx -= 8                                # bright slot unavailable -> the base hue
        self._color_cache[key] = idx
        return idx

    # Rough perceived luminance of each ANSI slot (0..1); -1 (terminal default) is assumed dark.
    _ANSI_LUM = {-1: 0.0, 0: 0.00, 1: 0.30, 2: 0.55, 3: 0.75, 4: 0.20, 5: 0.40, 6: 0.65, 7: 0.78,
                 8: 0.42, 9: 0.48, 10: 0.72, 11: 0.92, 12: 0.42, 13: 0.60, 14: 0.82, 15: 1.00}

    def _contrast(self, fg, bg):
        '''Low-color legibility guard: if `fg` would be (near-)invisible on `bg` — too little
        luminance separation, with the terminal default (-1) treated as dark — nudge it so text never
        vanishes (the classic "grey quantizes to black on a black terminal"). A hue is brightened to
        its bright variant where possible (keeps the meaning); greyscale goes to white/black. The
        theme's own default fg (-1) is left alone — the terminal guarantees it reads on its own bg.'''
        if fg == -1:
            return fg
        lf, lb = self._ANSI_LUM.get(fg, 0.5), self._ANSI_LUM.get(bg, 0.0)
        if abs(lf - lb) >= 0.28:
            return fg
        dark_bg = lb < 0.5
        if fg in (0, 7, 8, 15):                        # greyscale: no hue to preserve
            return (15 if self.have16 else 7) if dark_bg else 0
        if dark_bg:
            return fg + 8 if (self.have16 and fg < 8) else fg   # brighten the hue (8-color: keep it)
        return fg - 8 if fg >= 8 else fg                        # a light bg wants the darker hue

    def _pair(self, fg_idx, bg_idx, *, guard=True):
        if guard and self.lowcolor:                    # 8/16-color: keep text legible on its bg
            fg_idx = self._contrast(fg_idx, bg_idx)
        attr = self._pair_cache.get((fg_idx, bg_idx))
        if attr is None:
            n = self._next_pair
            if n > 255:                      # color_pair() only encodes 8 bits — pair >255 would WRAP
                return curses.A_NORMAL       # to another pair's colors; degrade instead of corrupt
            try:
                curses.init_pair(n, fg_idx, bg_idx)
                attr = curses.color_pair(n)
                self._next_pair += 1
            except curses.error:
                attr = curses.A_NORMAL
            self._pair_cache[(fg_idx, bg_idx)] = attr
        return attr

    def get(self, name):
        if self.mono:
            return curses.A_NORMAL
        idx = self._map.get(name)
        if idx is None:
            idx = self._entry(name)[0]
        return self._pair(idx, self.bg)

    def rgb_attr(self, rgb):
        '''An attr painting `rgb` as fg over the default background — for ad-hoc colors (the splash)
        outside the map. Shares the slot/pair allocator + caches and degrades gracefully.'''
        return curses.A_NORMAL if self.mono else self._pair(self._color(rgb), self.bg, guard=False)

    def rgb_pair(self, fg_rgb, bg_rgb):
        '''Like rgb_attr but over an explicit bg colour (a splash glyph over the liquid colour).'''
        return (curses.A_NORMAL if self.mono
                else self._pair(self._color(fg_rgb), self._color(bg_rgb), guard=False))

    def band(self, y, x, h, w):
        '''The gradient band index for a cell, along the top-left -> bottom-right diagonal.'''
        n = len(self._grad_bg)
        t = (y / max(1, h - 1) + x / max(1, w - 1)) / 2
        return min(n - 1, int(t * n))

    def style(self, element, y, x, h, w, *, selected=False, row=0, bg=None):
        '''The attr for a role at cell (y, x): its fg + flags, over its own bg if it declares one,
        else the active page's diagonal gradient (or the selected-row bar). `bg` (an rgb) forces the
        background for this cell — for a row tint (residual selection / profile member). `row` is
        accepted for call-site compatibility and ignored (roles are single styles now).'''
        fg, elem_bg, flags = self._entry(element)
        if self.mono:                                  # no color — keep the role's flags + reverse the bar
            return flags | (curses.A_REVERSE if selected else 0)
        g = not (flags & curses.A_REVERSE)             # reverse swaps fg/bg on screen -> skip the guard
        if bg is not None:
            return self._pair(fg, self._color(bg), guard=g) | flags
        if not self.gradient:
            base = self._pair(fg, self._sel_bg if selected else (elem_bg if elem_bg is not None
                                                                 else self.bg), guard=g)
            return base | flags
        b = self._sel_bg if selected else (elem_bg if elem_bg is not None
                                           else self._grad_bg[self.band(y, x, h, w)])
        return self._pair(fg, b, guard=g) | flags

    def at(self, name, y, x, h, w, *, selected=False, row=0):
        '''`name`'s fg over the gradient background (or the selected bar) — flags/bg ignored, for
        by-name row colorings (status column, etc).'''
        fg = self._entry(name)[0]
        if self.mono:
            return curses.A_REVERSE if selected else curses.A_NORMAL
        if not self.gradient:
            return self._pair(fg, self._sel_bg if selected else self.bg)
        bg = self._sel_bg if selected else self._grad_bg[self.band(y, x, h, w)]
        return self._pair(fg, bg)

    def fill(self, y, x, h, w, *, selected=False, bg=None):
        '''A blank-cell background attr (fg == bg) for painting the empty canvas behind text. `bg`
        (an rgb) forces a specific fill colour (a row tint), in every colour mode.'''
        if self.mono:
            return curses.A_REVERSE if selected else curses.A_NORMAL
        if bg is not None:
            idx = self._color(bg)
            return self._pair(idx, idx, guard=False)   # a solid block: fg == bg is intentional
        if not self.gradient:                          # no gradient (256/16, or truecolor grad-off):
            return self._pair(self._sel_bg, self._sel_bg, guard=False) if selected else curses.A_NORMAL
        b = self._sel_bg if selected else self._grad_bg[self.band(y, x, h, w)]
        return self._pair(b, b, guard=False)


# Which role to paint each component status.
STATUS_COLOR = {
    'installed': 'installed', 'outdated': 'outdated', 'partial': 'partial', 'missing': 'missing',
    'locked': 'locked', 'unsupported': 'unsupported', 'untrusted': 'untrusted', 'error': 'error',
}
