'''splash.py — the startup "liquid fill" progress animation.

While configsys inspects install state, the screen fills from the bottom up with an ASCII-block
liquid whose level tracks real progress (0 -> 100%), a random depth-gradient colour each run, a
wavy sloshing surface, and a few ASCII fish + bubbles once there's enough water to swim in. It is
purely cosmetic: the level is DRIVEN by the inspection worker's progress, never the other way.

Design notes:
- **Only when there's work.** The caller (tui.menu.run) runs inspection on a worker thread and
  only enters the splash if it's still going after a short threshold — a warm/fast run skips
  straight to the menu (see LiquidSplash.play's caller). This module just animates; the gating
  lives there.
- **Decoupled clock.** `LiquidSim.step(dt)` advances at a fixed frame rate and EASES the water
  toward the latest progress target, so even a slow `apt` check that stalls progress still shows
  gentle motion instead of a frozen bar.
- **Cheap colour.** Water cells are drawn as fg-only block glyphs over the default background, so
  the whole gradient costs one colour pair per depth band (not per cell) and stays well inside a
  256-colour terminal's budget. Everything degrades through Palette.rgb_attr.
- **Curves-free core.** `LiquidSim` holds no curses state and is deterministic given its rng, so
  the wave/fish/bubble logic is unit-tested directly; only `LiquidSplash.play` touches curses.
'''

import colorsys
import curses
import math
import time

from ..splashes import Splash, SplashFrame, register_splash

BLOCKS = ' ▁▂▃▄▅▆▇█'   # 8 partial-height blocks + space
FULL = '█'
BUBBLES = '°∘•'
BOAT = '⛵'            # a rare sailboat riding the surface
STAR_GLYPHS = ('·', '·', '·', '·', '✦', '✧', '⋆', '∗')   # mostly faint dots, some sparkles
COMET = '☄'            # a rare shooting comet that dives behind the water
MOONS = ('☽', '☾')    # first-quarter, last-quarter — at most one per run (or none)
SKELETONS = ('⤔', '⤕', '⤖', '⤗', '⤘')   # a fish skeleton may rarely rest on the sea floor

# Fish = [tail bracket][taper triangle][1–3 body blocks][head triangle]. The head points the swim
# direction; the OPPOSITE-facing triangle sits between body and tail to taper the body down into
# the fin. Two sizes — big (body ■, triangles ◀ ▶) and small (body ▪, triangles ◄ ►). The tail is
# any of the ornamental bracket pairs picked at random per fish: the CLOSING bracket (fans left)
# tails a right-swimmer, the OPENING bracket (fans right) a left-swimmer.  e.g. ❩◀■▶ / ◄▪►❰
_TAILS = ('❨❩', '❪❫', '❬❭', '❮❯', '❰❱', '❲❳', '❴❵')       # (opening, closing) pairs
_FISH_SIZES = (('■', '◀', '▶'), ('▪', '◄', '►'))           # body, left-tri, right-tri
FISH_RIGHT, FISH_LEFT = [], []
for _body, _lt, _rt in _FISH_SIZES:
    for _n in (1, 2, 3):                                    # 1–3 body blocks
        for _ob, _cb in _TAILS:                            # every tail bracket -> variety
            FISH_RIGHT.append(_cb + _lt + _body * _n + _rt)   # ❩◀■▶  tail, taper(◀), body, head(▶)
            FISH_LEFT.append(_lt + _body * _n + _rt + _ob)    # ◄▪►❰  head(◄), body, taper(►), tail
FISH_RIGHT, FISH_LEFT = tuple(FISH_RIGHT), tuple(FISH_LEFT)

FPS = 30.0
FRAME = 1.0 / FPS
MIN_DURATION = 0.6        # if we do show the splash, play at least this long (no one-frame flash)
FILL_EASE = 3.6           # water rises toward target at this rate (per second, exponential)


def random_palette(rng):
    '''A fresh liquid look each run: a random base hue, a deep (dark) -> surface (bright) value
    ramp, foam a touch brighter than the surface, and fish/bubble tints picked for contrast.
    Returns rgb tuples: (deep, surface, foam, fish, bubble).'''
    h = rng.random()
    deep = _hsv(h, 0.85, 0.26)
    surface = _hsv((h + rng.uniform(-0.04, 0.04)) % 1.0, 0.62, 0.96)
    foam = _hsv((h + 0.02) % 1.0, 0.30, 1.0)
    fish = _hsv((h + rng.uniform(0.4, 0.6)) % 1.0, 0.55, 0.92)     # roughly complementary
    bubble = _hsv((h + 0.5) % 1.0, 0.12, 1.0)
    return deep, surface, foam, fish, bubble


def _hsv(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return (round(r * 255), round(g * 255), round(b * 255))


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


class _Fish:
    __slots__ = ('x', 'row', 'vx', 'glyph', 'width')

    def __init__(self, x, row, vx, glyph):
        self.x, self.row, self.vx, self.glyph = x, row, vx, glyph
        self.width = len(glyph)


class _Bubble:
    __slots__ = ('x', 'y', 'vy', 'glyph')

    def __init__(self, x, y, vy, glyph):
        self.x, self.y, self.vy, self.glyph = x, y, vy, glyph


class _Boat:
    __slots__ = ('x', 'vx')

    def __init__(self, x, vx):
        self.x, self.vx = x, vx


class _Comet:
    __slots__ = ('x', 'y', 'vx', 'vy')       # sky coords: y measured from the TOP

    def __init__(self, x, y, vx, vy):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy


class _Skeleton:
    __slots__ = ('x', 'glyph')

    def __init__(self, x, glyph):
        self.x, self.glyph = x, glyph


class LiquidSim:
    '''Curses-free liquid state. Feed it progress via set_progress(frac 0..1); advance with
    step(dt); read surface_height(x) for the (fractional) water top at column x, plus `fish` and
    `bubbles`. Deterministic given `rng`.'''

    def __init__(self, w, h, rng):
        self.w = max(1, int(w))
        self.h = max(1, int(h))
        self.rng = rng
        self.level = 0.0          # eased current water level, in rows from the bottom
        self.target = 0.0         # progress-driven target level (rows), monotonic up
        self.t = 0.0              # elapsed animation time (for the wave phase)
        self.fish = []
        self.bubbles = []
        self.boats = []
        self.comets = []
        self.skeletons = []
        # a sky decoration fixed once per run: no moon, or exactly ONE quarter moon (never both)
        self.moon = rng.choice((None, None, MOONS[0], MOONS[1]))
        self.moon_pos = (rng.randint(0, max(0, self.h // 6)),
                         rng.randint(int(self.w * 0.12), max(1, int(self.w * 0.88))))
        # a fixed starfield scattered across the upper sky; each star gets a twinkle phase + a
        # colour index. Drawn behind the water, so the rising tide swallows them from the bottom.
        sky_rows = max(1, int(self.h * 0.72))
        self.stars = [(rng.randint(0, sky_rows - 1), rng.randint(0, self.w - 1),
                       rng.choice(STAR_GLYPHS), rng.uniform(0, 6.283), rng.randint(0, 2))
                      for _ in range(max(4, int(self.w * self.h * 0.01)))]
        # a gentle base swell + finer, faster ripples make a low but choppy, churning surface
        self._amp = min(0.7, self.h * 0.018 + 0.3)

    def set_progress(self, frac):
        '''Set the fill target from a 0..1 progress fraction. Monotonic — the water never recedes
        (a re-inspect that reports a smaller i/total mid-flight won't drop the level).'''
        frac = 0.0 if frac < 0 else 1.0 if frac > 1 else frac
        self.target = max(self.target, frac * self.h)

    @property
    def filled(self):
        '''True once the water has effectively reached its target (used to end the fill).'''
        return self.level >= self.target - 0.05

    def surface_height(self, x):
        '''Fractional water height (rows from bottom) at column x, including the surface wave.
        Below ~0 rows there's no wave (a dry screen stays flat).'''
        if self.level <= 0.01:
            return self.level
        a = self._amp
        wave = (math.sin(x * 0.55 + self.t * 2.7) * a          # base swell
                + math.sin(x * 0.31 - self.t * 2.0) * a * 0.45  # slower counter-roll
                + math.sin(x * 0.95 + self.t * 4.1) * a * 0.30)  # fast fine chop (the churn)
        return self.level + wave

    def step(self, dt):
        if dt <= 0:
            return
        self.t += dt
        # exponential ease toward the target (frame-rate independent)
        self.level += (self.target - self.level) * min(1.0, dt * FILL_EASE)
        self._step_fish(dt)
        self._step_bubbles(dt)
        self._step_boats(dt)
        self._step_comets(dt)
        self._step_skeletons(dt)

    # -- inhabitants -----------------------------------------------------

    def _depth_rows(self):
        return self.level

    def _step_fish(self, dt):
        depth = self._depth_rows()
        cap = max(1, self.w // 26)
        # spawn only once there's real water (>~30% of a shortish column, or a few rows)
        if depth >= min(self.h * 0.3, 4) and len(self.fish) < cap and self.rng.random() < dt * 1.1:
            self._spawn_fish(depth)
        alive = []
        for f in self.fish:
            f.x += f.vx * dt
            if -f.width - 1 <= f.x <= self.w + 1:
                alive.append(f)
        self.fish = alive

    def _spawn_fish(self, depth):
        from_left = self.rng.random() < 0.5
        speed = self.rng.uniform(3.5, 8.0)
        # keep fish inside the water: at least 1 row below the (mean) surface, above the floor
        top = max(1, int(depth) - 1)
        row = self.rng.randint(1, top) if top >= 1 else 1
        if from_left:
            self.fish.append(_Fish(-self.rng.uniform(0, 4), row, speed,
                                   self.rng.choice(FISH_RIGHT)))
        else:
            self.fish.append(_Fish(self.w + self.rng.uniform(0, 4), row, -speed,
                                   self.rng.choice(FISH_LEFT)))

    def _step_bubbles(self, dt):
        depth = self._depth_rows()
        if depth >= 2 and len(self.bubbles) < self.w // 8 + 1 and self.rng.random() < dt * 4:
            self.bubbles.append(_Bubble(self.rng.randint(0, self.w - 1), 0.0,
                                        self.rng.uniform(4.0, 9.0), self.rng.choice(BUBBLES)))
        alive = []
        for b in self.bubbles:
            b.y += b.vy * dt
            if b.y < depth:              # pops at the surface
                alive.append(b)
        self.bubbles = alive

    def _step_boats(self, dt):
        # a rare sailboat, only once there's a proper sea to sail on; at most one at a time
        if self._depth_rows() >= self.h * 0.4 and not self.boats and self.rng.random() < dt * 0.22:
            if self.rng.random() < 0.5:
                self.boats.append(_Boat(-2.0, self.rng.uniform(1.8, 3.2)))
            else:
                self.boats.append(_Boat(self.w + 2.0, -self.rng.uniform(1.8, 3.2)))
        alive = []
        for boat in self.boats:
            boat.x += boat.vx * dt
            if -3 <= boat.x <= self.w + 3:
                alive.append(boat)
        self.boats = alive

    def _step_comets(self, dt):
        # a rare comet streaks down across the sky and vanishes the moment it meets the water
        if not self.comets and self.rng.random() < dt * 0.28:
            from_left = self.rng.random() < 0.5
            x = -1.0 if from_left else self.w + 1.0
            vx = self.rng.uniform(9, 16) * (1 if from_left else -1)
            self.comets.append(_Comet(x, self.rng.uniform(0, self.h * 0.12), vx,
                                      self.rng.uniform(5, 9)))
        alive = []
        for c in self.comets:
            c.x += c.vx * dt
            c.y += c.vy * dt                                 # y grows downward (from the top)
            waterline_from_top = self.h - self.surface_height(c.x)
            if -2 <= c.x <= self.w + 2 and c.y < waterline_from_top:
                alive.append(c)                              # else it's off-screen or behind water
        self.comets = alive

    def _step_skeletons(self, dt):
        # a fish skeleton may (rarely) come to rest on the sea floor, then just lie there
        if (self._depth_rows() >= self.h * 0.5 and len(self.skeletons) < 1
                and self.rng.random() < dt * 0.08):
            self.skeletons.append(_Skeleton(self.rng.randint(0, self.w - 1),
                                            self.rng.choice(SKELETONS)))


class LiquidSplash(Splash):
    '''The built-in "liquid fill" splash: a curses driver around a LiquidSim. Precomputes a random
    colour ramp once, then render(frame) eases the fill toward frame.progress and paints the water,
    inhabitants, and sky. The host owns the loop (run_splash) — this just draws one frame and
    reports whether the water has reached its target. A reference implementation of the Splash ABI
    (configsys/splashes.py); it will move into its own code plugin.'''

    name = 'liquid'
    fps = FPS
    min_duration = MIN_DURATION

    def __init__(self, scr, pal, size, seed=None):
        super().__init__(scr, pal, size, seed)
        pal, rng = self.pal, self.rng
        self.sim = LiquidSim(self.w, self.h, rng)
        deep, surface, foam, fish, bubble = random_palette(rng)
        self.nbands = max(4, min(24, self.h))    # cap bands so pair usage is bounded by height
        ramp_rgb = [_lerp(deep, surface, k / (self.nbands - 1)) for k in range(self.nbands)]
        self._ramp = [pal.rgb_attr(c) for c in ramp_rgb]
        # fish/bubbles are painted OVER the liquid colour at their depth (not the black default),
        # so they look submerged — one pair per band, precomputed.
        self._fish = [pal.rgb_pair(fish, c) | curses.A_BOLD for c in ramp_rgb]
        self._bubble = [pal.rgb_pair(bubble, c) for c in ramp_rgb]
        # Froth is tinted by fill level so the crest isn't one flat bright line: a thin sliver is
        # whitest foam, a nearly-full cell sits closer to the water it's cresting over. The topmost
        # submerged row then blends halfway to foam, feathering the whitecap into the body over ~2
        # rows — softens the "blocky under the edge" hard step (can't de-quantize, but hides it).
        top_water = ramp_rgb[-1]
        self._froth = [0] + [pal.rgb_attr(_lerp(top_water, foam, 1 - (lvl - 1) / 7))
                             for lvl in range(1, 9)]     # indexed by BLOCKS level 1..8
        self._crest = pal.rgb_attr(_lerp(top_water, foam, 0.45))
        self._boat = pal.rgb_attr((240, 240, 248)) | curses.A_BOLD
        self._moon = pal.rgb_attr((245, 240, 205)) | curses.A_BOLD
        self._comet = pal.rgb_attr((215, 235, 255)) | curses.A_BOLD
        _star_cols = ((222, 226, 242), (240, 238, 224), (250, 250, 255))   # cool / warm / white
        self._star_dim = [pal.rgb_attr(_lerp((0, 0, 0), c, 0.5)) for c in _star_cols]
        self._star_bright = [pal.rgb_attr(c) | curses.A_BOLD for c in _star_cols]
        self._skel = pal.rgb_pair((226, 222, 205), ramp_rgb[0]) | curses.A_BOLD  # over deep water
        self._label_attr = pal.get('title') | curses.A_BOLD

    def _band_index(self, height_from_bottom):
        '''Ramp band for a height: deeper water (nearer the floor) is the dark end, the surface
        the bright end.'''
        ratio = 0.0 if self.h <= 1 else height_from_bottom / self.h
        idx = int(ratio * (self.nbands - 1) + 0.5)
        return max(0, min(self.nbands - 1, idx))

    def _band_attr(self, height_from_bottom):
        return self._ramp[self._band_index(height_from_bottom)]

    def render(self, frame):
        '''Draw ONE frame: ease the fill toward frame.progress, then paint sky + water + inhabitants
        + the centred label. The host refreshes; returns True once the water has reached its target
        (so the host may stop as soon as inspection is done too).'''
        self.sim.set_progress(frame.progress)
        self.sim.step(frame.dt)
        scr, h, w, sim = self.scr, self.h, self.w, self.sim
        scr.erase()
        # Sky first (stars, moon, comet), so the water drawn on top naturally hides whatever it
        # has risen over — the comet "disappears behind the water".
        for sy, sx, glyph, phase, ci in sim.stars:
            if 0 <= sy < h and 0 <= sx < w:
                bright = math.sin(sim.t * 2.5 + phase) > 0.25     # gentle twinkle
                self._safe_add(sy, sx, glyph,
                               self._star_bright[ci] if bright else self._star_dim[ci])
        if sim.moon:
            my, mx = sim.moon_pos
            if 0 <= my < h and 0 <= mx < w:
                self._safe_add(my, mx, sim.moon, self._moon)
        for c in sim.comets:
            cx, cy = int(c.x), int(c.y)
            if 0 <= cy < h and 0 <= cx < w:
                self._safe_add(cy, cx, COMET, self._comet)
        for x in range(w):
            top = sim.surface_height(x)          # rows of water at this column
            full = int(top)
            frac = top - full
            for hb in range(min(full, h)):       # solid water below the surface
                row = h - 1 - hb
                if 0 <= row < h:
                    # feather the crest: topmost submerged row blends toward foam (only where there
                    # IS froth above it), so the whitecap dissolves into the body over ~2 rows
                    crest = hb == full - 1 and 0 < frac
                    self._safe_add(row, x, FULL, self._crest if crest else self._band_attr(hb))
            if 0 < frac and full < h:             # the wavy surface cell (partial block)
                row = h - 1 - full
                lvl = max(1, min(8, int(frac * 8) + 1))
                self._safe_add(row, x, BLOCKS[lvl], self._froth[lvl])
        for b in sim.bubbles:                     # bubbles rising through the water
            row = h - 1 - int(b.y)
            if 0 <= row < h and 0 <= int(b.x) < w:
                self._safe_add(row, int(b.x), b.glyph, self._bubble[self._band_index(int(b.y))])
        for f in sim.fish:                        # fish swimming at their depth
            row = h - 1 - f.row
            if 0 <= row < h:
                attr = self._fish[self._band_index(f.row)]   # over the liquid colour at its depth
                for i, ch in enumerate(f.glyph):
                    cx = int(f.x) + i
                    if 0 <= cx < w:
                        self._safe_add(row, cx, ch, attr)
        for sk in sim.skeletons:                  # a skeleton resting on the sea floor (bottom row)
            if 0 <= sk.x < w:
                self._safe_add(h - 1, sk.x, sk.glyph, self._skel)
        for boat in sim.boats:                    # a rare sailboat riding on top of the surface
            bx = int(boat.x)
            if 0 <= bx < w:
                row = max(0, h - 1 - int(sim.surface_height(boat.x)) - 1)
                self._safe_add(row, bx, BOAT, self._boat)
        if frame.label:
            self._draw_label(frame)
        return sim.filled

    def _label_text(self, counts, label):
        i, total = counts
        if not total:
            return f'{label}…'
        pct = int(i / total * 100)
        return f'{label}:   {i}/{total} ({pct}%)'

    def _draw_label(self, frame):
        text = self._label_text(frame.counts, frame.label)
        y = max(0, self.h // 2)
        x = max(0, (self.w - len(text)) // 2)
        for k, ch in enumerate(text):
            if x + k < self.w:
                self._safe_add(y, x + k, ch, self._label_attr)

    def _safe_add(self, y, x, ch, attr):
        # writing the last cell throws (cursor can't advance past it) — a curses fact of life.
        try:
            self.scr.addstr(y, x, ch, attr)
        except curses.error:
            pass


register_splash(LiquidSplash, builtin=True)


# -- the host frame loop (shared by every splash provider) ----------------------------------------

def _draw_progress_text(scr, pal, label, counts, h, w):
    '''The host's plain progress line — shown after a skip, and the safe fallback for any splash.
    A clean screen with a centred "<label>: i/total (pct%)" so cancelling the animation never
    hides the real state.'''
    i, total = counts
    text = (f'{label}…' if not total else
            f'{label}:   {i}/{total} ({int(i / total * 100)}%)') if label else ''
    scr.erase()
    if text:
        y, x = max(0, h // 2), max(0, (w - len(text)) // 2)
        try:
            scr.addstr(y, x, text[:max(0, w - x)], pal.get('title') | curses.A_BOLD)
        except curses.error:
            pass


def run_splash(scr, pal, provider_cls, *, is_done, frac, counts, label, deadline=None, seed=None):
    '''Drive a Splash provider's frame loop until inspection is done AND the animation is at rest
    (or a hard `deadline`). The provider only draws one frame from a SplashFrame; the HOST owns the
    clock, the skip key, and the plain-text fallback: a keypress CANCELS the animation but a plain
    progress line keeps updating on a clean screen until inspection actually finishes, so dropping
    the eye-candy never hides the real state. `frac()`/`counts()`/`is_done()` are polled each frame;
    dt-based timing means a slow frame just eases further, never desyncs. Never raises for a
    misbehaving provider frame — a broken render falls back to the text line.'''
    h, w = scr.getmaxyx()
    provider = provider_cls(scr, pal, (h, w), seed)
    fps = getattr(provider_cls, 'fps', 30.0) or 30.0
    frame_dt = 1.0 / fps
    min_dur = getattr(provider_cls, 'min_duration', MIN_DURATION)
    scr.nodelay(True)
    try:
        start = last = time.monotonic()
        animate = True
        while True:
            now = time.monotonic()
            dt = now - last
            last = now
            done = is_done()
            frame = SplashFrame(progress=(1.0 if done else frac()), counts=counts(),
                                label=label, dt=dt, elapsed=now - start, done=done)
            at_rest = False
            if animate:
                try:
                    at_rest = bool(provider.render(frame))
                except Exception:                     # noqa: BLE001 — a broken splash never bricks startup
                    animate = False
                    _draw_progress_text(scr, pal, label, frame.counts, h, w)
                if animate and scr.getch() != -1:     # Esc/any key -> drop the animation, keep text
                    animate = False
            else:
                _draw_progress_text(scr, pal, label, frame.counts, h, w)
            scr.noutrefresh()
            curses.doupdate()
            if deadline is not None and now >= deadline:
                return
            if animate:
                if done and at_rest and (now - start) >= min_dur:
                    return
            elif done:                                # text mode: leave as soon as it's finished
                return
            slack = frame_dt - (time.monotonic() - now)
            if slack > 0:
                time.sleep(slack)
    finally:
        scr.nodelay(False)
