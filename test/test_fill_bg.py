'''_fill_bg caches the gradient SEGMENT GEOMETRY (pure position math) but must recompute pal.fill()
every frame — color pairs are recycled per frame (Palette.new_frame), so caching the resolved attr
made a cached pair number map to the wrong colour a frame later (banding/skew). Regression guard.'''

from configsys.tui import menu


class _FakePal:
    _grad_bg = [0, 1, 2, 3, 4]                    # 5 bands

    def __init__(self):
        self.frame = 0

    def band(self, y, x, h, w):
        n = len(self._grad_bg)
        t = (y / max(1, h - 1) + x / max(1, w - 1)) / 2
        return min(n - 1, int(t * n))

    def fill(self, y, x, h, w, **k):
        # a frame-varying attr: same band, but the "pair number" differs per frame (as real
        # new_frame() recycling would produce). A correct _fill_bg reflects the CURRENT frame.
        return (self.frame, self.band(y, x, h, w))


class _FakeScr:
    def __init__(self):
        self.painted = []

    def addstr(self, y, x, blanks, attr):
        self.painted.append((y, x, len(blanks), attr))


def test_fill_bg_recomputes_fill_each_frame_not_a_cached_attr():
    menu._FILL_BG_SEGS.clear()
    pal, scr = _FakePal(), _FakeScr()
    pal.frame = 1
    menu._fill_bg(scr, pal, 8, 20)
    frame1 = list(scr.painted)
    scr.painted = []
    pal.frame = 2
    menu._fill_bg(scr, pal, 8, 20)
    frame2 = list(scr.painted)

    geom1 = [(y, x, w) for (y, x, w, _a) in frame1]
    geom2 = [(y, x, w) for (y, x, w, _a) in frame2]
    assert geom1 == geom2 and geom1                       # segment GEOMETRY is stable (cached)
    attrs1 = [a for (*_g, a) in frame1]
    attrs2 = [a for (*_g, a) in frame2]
    assert attrs1 != attrs2                               # but the attrs are THIS frame's (fresh pairs)
    assert all(a[0] == 1 for a in attrs1) and all(a[0] == 2 for a in attrs2)


def test_fill_bg_covers_every_row_and_paints_the_gradient_bands():
    menu._FILL_BG_SEGS.clear()
    pal, scr = _FakePal(), _FakeScr()
    menu._fill_bg(scr, pal, 6, 24)
    rows = {y for (y, _x, _w, _a) in scr.painted}
    assert rows == set(range(6))                          # every row painted
    bands = {a[1] for (*_g, a) in scr.painted}
    assert len(bands) > 1                                 # a real gradient (several distinct bands)
