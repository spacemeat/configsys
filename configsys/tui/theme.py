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
        for name, rgb in SEMANTIC.items():
            self.attrs[name] = self._alloc(rgb)

    def _alloc(self, rgb):
        idx = rgb_to_256(*rgb) if self.have256 else rgb_to_basic8(*rgb)
        self._pair += 1
        try:
            curses.init_pair(self._pair, idx, self.bg)
        except curses.error:
            return curses.A_NORMAL
        return curses.color_pair(self._pair)

    def get(self, name):
        return self.attrs.get(name, curses.A_NORMAL)


# Which palette color to paint each component status.
STATUS_COLOR = {
    'installed': 'installed',
    'outdated': 'outdated',
    'partial': 'partial',
    'missing': 'missing',
    'locked': 'locked',
    'unsupported': 'unsupported',
    'error': 'error',
}
