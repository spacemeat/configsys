'''surface.py — the one drawing sink the TUI paints through.

The painters (`_draw_*`, and the Screen `.draw()` methods that replace them) only ever touch a
handful of window operations: `getmaxyx`, `erase`, `addstr`, `move`, `refresh`, and `derwin` (the
Theme screen renders sub-pages into a sub-window). A Surface is exactly that contract, so a painter
can render to a real curses window OR to an off-screen buffer without knowing which.

- `CursesSurface` wraps a curses `stdscr`/window and delegates verbatim (a thin, transparent shim —
  the real terminal path).
- `BufferSurface` records every drawn cell into a `{(y, x): Cell}` grid and does nothing else. It is
  what makes the TUI renderable headlessly: the render-equivalence harness paints a screen from a
  fixed state into a BufferSurface and compares the grid, and it is the seam an eventual
  headless/SDK mode would drive.

Palette is untouched by any of this — its `style/at/fill/get/rgb_*` methods only COMPUTE attrs, they
never draw, so the attr a painter hands to `surface.addstr(...)` is opaque to the Surface (a curses
int on the real path, a descriptor token in the harness).
'''

from collections import namedtuple

# one painted character cell: the glyph and the opaque attr it was drawn with.
Cell = namedtuple('Cell', 'char attr')


class CursesSurface:
    '''A transparent shim over a curses window. Delegates every op to the underlying window, so the
    real terminal path behaves exactly as direct `stdscr` use did.'''

    __slots__ = ('win',)

    def __init__(self, win):
        self.win = win

    def getmaxyx(self):
        return self.win.getmaxyx()

    def erase(self):
        self.win.erase()

    def addstr(self, y, x, s, attr=0):
        self.win.addstr(y, x, s, attr)

    def move(self, y, x):
        self.win.move(y, x)

    def refresh(self):
        self.win.refresh()

    def derwin(self, h, w, y, x):
        return CursesSurface(self.win.derwin(h, w, y, x))


class BufferSurface:
    '''An off-screen window that records painted cells instead of drawing. `cells` maps (y, x) ->
    Cell(char, attr) for every non-blank glyph written within bounds; a later write to the same cell
    overwrites it, exactly as curses would. `derwin` returns a view that offsets writes into this same
    grid, so a painter that renders sub-pages (Theme) records at absolute coordinates.'''

    __slots__ = ('h', 'w', 'cells', '_cursor', '_oy', '_ox', '_parent')

    def __init__(self, h, w, *, _parent=None, _oy=0, _ox=0):
        self.h = h
        self.w = w
        # A sub-surface (derwin) shares its parent's grid; a root owns its own.
        self._parent = _parent
        self._oy = _oy
        self._ox = _ox
        self.cells = _parent.cells if _parent is not None else {}
        self._cursor = (0, 0)

    def getmaxyx(self):
        return (self.h, self.w)

    def erase(self):
        # curses erase clears the whole window; on a root that is the whole grid. A sub-window erase
        # clears only its own rectangle in the shared grid.
        if self._parent is None:
            self.cells.clear()
        else:
            for yy in range(self.h):
                for xx in range(self.w):
                    self.cells.pop((self._oy + yy, self._ox + xx), None)

    def addstr(self, y, x, s, attr=0):
        # Clip to this surface's own bounds (curses would raise past the edge; the painters pre-clip,
        # and _put swallows curses.error, so silently dropping out-of-bounds writes matches behavior).
        if y < 0 or y >= self.h:
            return
        for i, ch in enumerate(s):
            cx = x + i
            if cx < 0:
                continue
            if cx >= self.w:
                break
            self.cells[(self._oy + y, self._ox + cx)] = Cell(ch, attr)

    def move(self, y, x):
        self._cursor = (y, x)

    def refresh(self):
        pass

    def derwin(self, h, w, y, x):
        return BufferSurface(h, w, _parent=self, _oy=self._oy + y, _ox=self._ox + x)

    # -- harness helpers ---------------------------------------------------

    def grid(self):
        '''The painted cells as a sorted list of (y, x, char, attr) — a stable, comparable snapshot.'''
        return [(y, x, c.char, c.attr) for (y, x), c in sorted(self.cells.items())]

    def text_rows(self):
        '''The painted glyphs as plain text rows (attrs dropped) — for eyeballing a capture.'''
        if not self.cells:
            return []
        rows = []
        maxy = max(y for y, _ in self.cells)
        for y in range(maxy + 1):
            xs = [x for (yy, x) in self.cells if yy == y]
            if not xs:
                rows.append('')
                continue
            line = [' '] * (max(xs) + 1)
            for x in xs:
                line[x] = self.cells[(y, x)].char
            rows.append(''.join(line).rstrip())
        return rows
