'''theme.py — color for the TUI, 24-bit when the terminal allows it.

Preference order per color: (1) true 24-bit via `curses.init_color` (an exact RGB defined into a
private palette slot) when the terminal can change colors — smooth, faithful, darks stay dark;
(2) the xterm-256 cube approximation otherwise; (3) the basic 8 on a <256-color terminal. The
diagonal background GRADIENT is only painted when we have true 24-bit (otherwise the cube turns
very-dark purples into a few bright blocks) — off it, the menu just uses the default background.

Colors are user-overridable: a `theme:` section in the config (see Config.theme / resolve_theme)
supplies hex or [r,g,b] values for any semantic color and for the gradient endpoints.
'''

import curses

# Default semantic RGB (0-255). A `theme.colors.<name>` override replaces any of these.
SEMANTIC = {
    'header': (120, 200, 255),
    'title': (235, 235, 235),
    'installed': (90, 200, 120),
    'outdated': (230, 190, 70),
    'partial': (90, 190, 205),
    'missing': (150, 150, 150),
    'locked': (110, 165, 255),
    'unsupported': (110, 110, 110),
    'untrusted': (220, 140, 60),   # a plugin driver present but not yet trusted (action needed)
    'error': (235, 95, 95),
    'op_install': (90, 200, 120),
    'op_upgrade': (230, 190, 70),
    'op_remove': (235, 95, 95),
    'op_lock': (110, 165, 255),
    'op_unlock': (120, 210, 210),
    'dim': (120, 120, 120),
    'accent': (200, 140, 240),
}

# Default menu background: a very dark purple diagonal (top-left -> bottom-right), quantized into
# GRAD_BANDS steps; the selected row is a brighter solid bar. Overridable via theme.gradient.
GRAD_BANDS = 12
GRAD_A = (22, 10, 34)     # top-left    — dark purple
GRAD_B = (5, 2, 10)       # bottom-right — near-black
SEL_BG = (58, 34, 88)     # selected-row bar


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


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


def resolve_theme(theme):
    '''Merge a `theme:` override dict onto the defaults. Returns (colors {name:(r,g,b)}, grad_from,
    grad_to, grad_sel, gradient_enabled). Pure — no curses. `theme.colors.<name>` overrides a
    semantic color; `theme.gradient.{from,to,selected}` the gradient; `theme.gradient: false` (or
    `.enabled: false`) turns the background gradient off.'''
    colors = dict(SEMANTIC)
    ga, gb, gs, enabled = GRAD_A, GRAD_B, SEL_BG, True
    if isinstance(theme, dict):
        for name, val in (theme.get('colors') or {}).items():
            rgb = parse_color(val)
            if rgb and name in colors:
                colors[name] = rgb
        g = theme.get('gradient')
        if g is False or (isinstance(g, dict) and g.get('enabled') in (False, 'false', 'no')):
            enabled = False
        if isinstance(g, dict):
            ga = parse_color(g.get('from')) or ga
            gb = parse_color(g.get('to')) or gb
            gs = parse_color(g.get('selected')) or gs
    return colors, ga, gb, gs, enabled


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
    def __init__(self, theme=None):
        curses.start_color()
        self.bg = -1
        try:
            curses.use_default_colors()
        except curses.error:
            self.bg = curses.COLOR_BLACK
        self.have256 = curses.COLORS >= 256
        # True 24-bit reaches us two ways: a direct-color terminal (COLORS == 2**24, e.g.
        # TERM=xterm-direct) where the color NUMBER is the packed RGB, or a palette-redefinable one
        # (init_color / can_change_color, e.g. xterm-256color with `ccc`). Either lets us paint the
        # background gradient with faithful darks; without it we fall back (cube fg, no gradient) —
        # the 256 cube crushes dark purples into a few bright blocks.
        self.direct = curses.COLORS >= (1 << 24)
        try:
            self.truecolor = self.direct or (self.have256 and curses.can_change_color())
        except curses.error:
            self.truecolor = self.direct

        colors, ga, gb, gs, grad_enabled = resolve_theme(theme)
        self._next_color = 16          # private palette-slot allocator (truecolor mode)
        self._next_pair = 1
        self._color_cache = {}         # rgb -> palette index
        self._pair_cache = {}          # (fg_idx, bg_idx) -> attr
        self._fg = {}                  # semantic name -> fg palette index
        self.attrs = {}
        for name, rgb in colors.items():
            idx = self._color(rgb)
            self._fg[name] = idx
            self.attrs[name] = self._pair(idx, self.bg)

        self.gradient = self.truecolor and grad_enabled
        if self.gradient:
            self._grad_bg = [self._color(_lerp(ga, gb, k / (GRAD_BANDS - 1))) for k in range(GRAD_BANDS)]
            self._sel_bg = self._color(gs)

    def _color(self, rgb):
        '''A palette index for an RGB: an exact custom slot via init_color when we have true
        24-bit; else the nearest xterm-256 cube (or basic-8) index. Cached + deduped.'''
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
        return self.attrs.get(name, curses.A_NORMAL)

    # -- gradient background ---------------------------------------------

    def band(self, y, x, h, w):
        '''The gradient band [0, GRAD_BANDS) for a cell, along the top-left -> bottom-right diagonal.'''
        t = (y / max(1, h - 1) + x / max(1, w - 1)) / 2
        return min(GRAD_BANDS - 1, int(t * GRAD_BANDS))

    def at(self, name, y, x, h, w, *, selected=False):
        '''`name`'s fg over the gradient background at cell (y, x) — or the selected-row bar. With
        no gradient, the plain semantic pair (reverse if selected).'''
        if not self.gradient:
            return self.get(name) | (curses.A_REVERSE if selected else 0)
        bg = self._sel_bg if selected else self._grad_bg[self.band(y, x, h, w)]
        return self._pair(self._fg.get(name, self._fg.get('dim')), bg)

    def fill(self, y, x, h, w, *, selected=False):
        '''A blank-cell background attr (fg == bg) for painting the empty canvas behind the text.'''
        if not self.gradient:
            return curses.A_REVERSE if selected else curses.A_NORMAL
        bg = self._sel_bg if selected else self._grad_bg[self.band(y, x, h, w)]
        return self._pair(bg, bg)


# Which palette color to paint each component status.
STATUS_COLOR = {
    'installed': 'installed',
    'outdated': 'outdated',
    'partial': 'partial',
    'missing': 'missing',
    'locked': 'locked',
    'unsupported': 'unsupported',
    'untrusted': 'untrusted',
    'error': 'error',
}
