'''theme.py — 24-bit-intent color for the TUI, realized on the xterm-256 cube.

We map semantic RGB colors to the terminal's 256-color palette (no init_color, so
the user's palette is never mutated and teardown is clean). On <256-color
terminals we fall back to the basic 8. Colors are allocated as curses pairs
against the default background.
'''

import curses

# Semantic RGB (0-255). Tuned to read well in both light and dark terminals.
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


def rgb_to_256(r, g, b):
    if r == g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return 232 + round((r - 8) / 247 * 24)
    return (16
            + 36 * round(r / 255 * 5)
            + 6 * round(g / 255 * 5)
            + round(b / 255 * 5))


def rgb_to_basic8(r, g, b):
    # nearest of the 8 base colors by dominant channel / brightness
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


# Experimental menu background: a very dark diagonal gradient (top-left -> bottom-right), dark
# enough not to fight the text. Quantized into GRAD_BANDS steps; the selected row gets a brighter
# solid bar instead of the gradient. 256-color only (falls back to the default bg otherwise).
GRAD_BANDS = 8
GRAD_A = (26, 12, 38)     # top-left    — a smart dark purple
GRAD_B = (7, 3, 13)       # bottom-right — near-black purple
SEL_BG = (72, 44, 104)    # selected-row bar


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


class Palette:
    def __init__(self):
        curses.start_color()
        self.bg = -1
        try:
            curses.use_default_colors()
        except curses.error:
            self.bg = curses.COLOR_BLACK
        self.have256 = curses.COLORS >= 256
        self._pair = 0
        self.attrs = {}
        self._fg = {}                              # semantic name -> its fg color index
        for name, rgb in SEMANTIC.items():
            self.attrs[name] = self._alloc(name, rgb)
        # gradient state (256-color only): background band indices + a lazy (fg,bg)-pair cache
        self.gradient = self.have256
        self._grad_bg = ([rgb_to_256(*_lerp(GRAD_A, GRAD_B, k / (GRAD_BANDS - 1)))
                          for k in range(GRAD_BANDS)] if self.gradient else [])
        self._sel_bg = rgb_to_256(*SEL_BG) if self.gradient else self.bg
        self._combo = {}                           # (fg_idx, bg_idx) -> attr

    def _alloc(self, name, rgb):
        idx = rgb_to_256(*rgb) if self.have256 else rgb_to_basic8(*rgb)
        self._fg[name] = idx
        self._pair += 1
        try:
            curses.init_pair(self._pair, idx, self.bg)
        except curses.error:
            return curses.A_NORMAL
        return curses.color_pair(self._pair)

    def get(self, name):
        return self.attrs.get(name, curses.A_NORMAL)

    # -- gradient background ---------------------------------------------

    def band(self, y, x, h, w):
        '''The gradient band [0, GRAD_BANDS) for a cell, along the top-left -> bottom-right diagonal.'''
        t = (y / max(1, h - 1) + x / max(1, w - 1)) / 2
        return min(GRAD_BANDS - 1, int(t * GRAD_BANDS))

    def _combo_pair(self, fg_idx, bg_idx):
        attr = self._combo.get((fg_idx, bg_idx))
        if attr is None:
            self._pair += 1
            try:
                curses.init_pair(self._pair, fg_idx, bg_idx)
                attr = curses.color_pair(self._pair)
            except curses.error:
                attr = curses.A_NORMAL
            self._combo[(fg_idx, bg_idx)] = attr
        return attr

    def at(self, name, y, x, h, w, *, selected=False):
        '''`name`'s fg over the gradient background at cell (y, x) — or the selected-row bar. Off
        the gradient (no 256-color) falls back to the plain semantic pair (reverse if selected).'''
        if not self.gradient:
            return self.get(name) | (curses.A_REVERSE if selected else 0)
        bg = self._sel_bg if selected else self._grad_bg[self.band(y, x, h, w)]
        return self._combo_pair(self._fg.get(name, self._fg.get('dim')), bg)

    def fill(self, y, x, h, w, *, selected=False):
        '''A blank-cell background attr at (y, x): the gradient (or the selected bar) with an
        invisible fg (fg == bg), for painting the empty canvas behind the text.'''
        if not self.gradient:
            return curses.A_REVERSE if selected else curses.A_NORMAL
        bg = self._sel_bg if selected else self._grad_bg[self.band(y, x, h, w)]
        return self._combo_pair(bg, bg)


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
