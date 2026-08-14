'''splashes.py — the SPLASH provider ABI (curses-free surface).

A "splash" is a startup wait-screen animation. The HOST (configsys.tui.splash.run_splash) owns the
frame loop: it constructs the provider once, then calls render(frame) at ~fps, feeding it live
progress, and takes care of the skip key, the deadline, and the safe plain-text fallback. A
provider just draws ONE frame from the minimal data in a SplashFrame — the least a plugin needs to
paint an animated wait screen.

Third-party splashes ship as trusted CODE plugins, exactly like drivers: a plugin's `code:` module
exports `SPLASHES = [YourSplash, ...]` (parallel to `DRIVERS = [...]`), and the trusted loader
registers them. Pick one with the `splash:` machine setting.

This module is curses-free so it can sit on the frozen plugin surface — configsys.plugins
re-exports `Splash`, `SplashFrame`, and `register_splash`. Concrete providers import curses
themselves and draw onto the window handed to them.
'''

from collections import namedtuple

# Per-frame data handed to Splash.render — the minimal set for an animated wait screen:
#   progress : float 0..1 — the fraction of inspection done (1.0 once done); drive the fill off this
#   counts   : (i, total) integers for a numeric caption (total may be 0 while still unknown)
#   label    : str | None — a short caption, e.g. "checking install state"
#   dt       : float seconds since the previous frame — animate off this to stay frame-rate independent
#   elapsed  : float seconds since the splash started
#   done     : bool — inspection has finished (the host stops once the splash is ALSO at rest)
SplashFrame = namedtuple('SplashFrame', 'progress counts label dt elapsed done')


class Splash:
    '''Base class for a startup wait-screen animation. Subclass it, set a class-level `name`, and
    implement render(frame).

    The host constructs you once as `Splash(scr, pal, size, seed)`:
      - `scr`  a curses window to draw on (use scr.addstr(y, x, ch, attr));
      - `pal`  a configsys Palette — pal.rgb_attr(rgb) / pal.rgb_pair(fg, bg) / pal.get(role)
               yield curses attrs, so you never allocate colours yourself;
      - `size` (h, w) of the screen;
      - `seed` seeds self.rng for a deterministic (unit-testable) look.
    Then it calls render(frame) each frame. Draw onto self.scr and DO NOT refresh — the host does
    the doupdate. Return True once the animation has reached a natural resting point (e.g. the fill
    is full) so the host may stop as soon as inspection is also done; a falsey return keeps going.

    Class attributes tune the host loop: `fps` (target frame rate) and `min_duration` (if shown at
    all, play at least this long — no one-frame flash).

    RAW (truecolor) providers: set class attr `raw = True` to bypass curses' colour model entirely
    (curses `color_pair()` caps at 256 pairs — too few for a smooth 24-bit gradient). A raw
    provider's `render(frame)` RETURNS a str of ANSI (positioned from the top-left, e.g. per-row
    `\\033[<row>;1H…` with `\\033[38;2;r;g;bm`/`\\033[48;2;r;g;bm` SGR); the host writes it straight
    to the terminal and skips its own curses repaint for that frame (so don't touch self.scr). `pal`
    is unused. Set `self.at_rest = True` when the animation has settled (default: at rest once
    inspection is done). The host still owns the clock, skip key, deadline, and the text fallback.'''
    name = None
    fps = 30.0
    min_duration = 0.6
    raw = False                     # True -> render() returns an ANSI string; host writes it raw (truecolor)

    def __init__(self, scr, pal, size, seed=None):
        import random
        self.scr = scr
        self.pal = pal
        self.h, self.w = size
        self.rng = random.Random(seed)

    def render(self, frame):
        raise NotImplementedError('a Splash must implement render(frame)')


_SPLASHES = {}                     # name -> Splash subclass
_BUILTIN_SPLASH_NAMES = set()      # names shipped in core (for conflict messaging)


def register_splash(cls, *, builtin=False):
    '''Register a Splash subclass under `cls.name`, so `splash: <name>` can select it. Usable as a
    decorator (returns the class). A code plugin exports `SPLASHES = [cls, ...]` and the trusted
    loader calls this for each; `builtin=True` marks a core-shipped provider (for conflict notes).'''
    name = getattr(cls, 'name', None)
    if not name:
        raise ValueError(f'{cls!r} has no `name` — a Splash must set a class-level name')
    _SPLASHES[name] = cls
    if builtin:
        _BUILTIN_SPLASH_NAMES.add(name)
    return cls


def get_splash(name):
    '''The registered Splash subclass for `name`, or None if unknown/unregistered.'''
    return _SPLASHES.get(name)


def splash_names():
    '''Sorted names of every registered splash (built-ins + trusted plugin providers).'''
    return sorted(_SPLASHES)


def random_splash(exclude=None, rng=None):
    '''A random registered splash NAME, excluding `exclude` (e.g. the built-in default) — this is
    what `splash: random` resolves to each run. None if nothing else is registered. Pass an `rng`
    (a random.Random) to make the choice deterministic/testable.'''
    import random as _random
    pool = [n for n in splash_names() if n != exclude]
    if not pool:
        return None
    return (rng or _random).choice(pool)
