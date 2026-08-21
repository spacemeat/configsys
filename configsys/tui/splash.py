'''splash.py — the splash HOST loop + the built-in `braille-bar` default.

configsys splashes are provider plugins (see configsys/splashes.py for the ABI). This module owns
the FRAME LOOP shared by every provider (`run_splash`): it constructs the chosen `Splash`, drives
it at its frame rate while feeding live progress, and owns the skip key, the deadline, and the safe
plain-text fallback. The only provider shipped in core is `braille-bar` — a light braille spinner +
determinate progress bar (no trust, adds no time) that is both the default when `splash:` is unset
and the universal fallback. Fancier splashes (e.g. the ASCII-water `ocean` fill) live in code
plugins like configsys-splash-ocean.
'''

import curses
import re
import sys
import time

from ..splashes import Splash, SplashFrame, register_splash
from .theme import rgb_to_256, rgb_to_basic8


def _tty_write(s):
    '''Write a raw ANSI string straight to the terminal — for `raw` (truecolor) splashes that bypass
    curses' 256-pair colour model. Best-effort; never raises into the splash loop.'''
    try:
        sys.stdout.write(s)
        sys.stdout.flush()
    except (OSError, ValueError):
        pass


_SGR_RE = re.compile('\x1b\\[([0-9;]*)m')


def _sgr_encode(r, g, b, is_bg, depth):
    '''One 24-bit SGR run -> the capped depth. 256 -> the xterm cube (38;5/48;5); 16/8 -> the base
    ANSI codes (30-37/40-47, + the bright 90-97/100-107 in 16-color for luminous colors).'''
    if depth == '256':
        return f'{48 if is_bg else 38};5;{rgb_to_256(r, g, b)}'
    idx = rgb_to_basic8(r, g, b)                        # 0..7 nearest hue
    if depth == '16' and max(r, g, b) >= 150:           # a luminous color -> the bright ANSI pair
        return str((100 if is_bg else 90) + idx)
    return str((40 if is_bg else 30) + idx)


def _sgr_downconvert(s, pal):
    '''Rewrite 24-bit color SGR sequences in a RAW splash's output down to the Palette's resolved
    depth, so a `raw` (truecolor) splash honors --color/--nocolor like everything else. A no-op under
    real truecolor (the common case — early return, no scanning). Non-color SGR, cursor moves, and
    resets pass through untouched. `mono` strips color entirely (structural attrs survive).'''
    if pal is None or getattr(pal, 'truecolor', False) or getattr(pal, 'direct', False):
        return s                                        # keep the 24-bit output as-is
    depth = ('mono' if getattr(pal, 'mono', False) else
             '256' if getattr(pal, 'have256', False) else '16' if getattr(pal, 'have16', False) else '8')

    def conv(m):
        toks = (m.group(1) or '0').split(';')
        out, i = [], 0
        while i < len(toks):
            t = toks[i]
            if t in ('38', '48') and toks[i + 1:i + 2] == ['2'] and i + 4 < len(toks):
                try:
                    rgb = int(toks[i + 2]), int(toks[i + 3]), int(toks[i + 4])
                except ValueError:
                    out.append(t); i += 1; continue
                i += 5
                if depth != 'mono':                     # mono: drop the color run entirely
                    out.append(_sgr_encode(*rgb, t == '48', depth))
            else:
                out.append(t); i += 1
        return '\x1b[' + ';'.join(out) + 'm'

    return _SGR_RE.sub(conv, s)

MIN_DURATION = 0.6              # a plugin splash floor (no one-frame flash); the default overrides it to 0
DEFAULT_SPLASH = 'braille-bar'  # the built-in, trust-free default when `splash:` is unset
_SPINNER = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'   # a braille spinner, 12 steps/sec


def _draw_progress_text(scr, pal, label, counts, h, w):
    '''The host's plain progress line — the safe STATIC fallback after a skip or a broken provider.
    A clean screen with a centred "<label>: i/total (pct%)" so cancelling an animation never hides
    the real state. (The default `braille-bar` splash itself is the livelier BrailleBarSplash below.)'''
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


class BrailleBarSplash(Splash):
    '''The built-in default: a calm centred wait screen — a braille spinner, the label + counts, and
    a slim determinate progress bar tracking real progress. Trust-free, always available, and adds
    no time of its own (min_duration 0, so it exits the moment inspection is done). The fancier
    animations (the ASCII-water `ocean` fill, …) live in code plugins. Reference for the Splash ABI.'''
    name = DEFAULT_SPLASH
    min_duration = 0.0

    def _add(self, y, x, s, attr):
        try:
            self.scr.addstr(y, x, s, attr)
        except curses.error:
            pass

    def render(self, frame):
        scr, h, w = self.scr, self.h, self.w
        scr.erase()
        i, total = frame.counts
        label = frame.label or 'working'
        spin = _SPINNER[int(frame.elapsed * 12) % len(_SPINNER)]
        pct = int(frame.progress * 100)
        head = f'{spin}  {label}' + (f'   {i}/{total} ({pct}%)' if total else '')
        title = self.pal.get('title') | curses.A_BOLD
        y = max(0, h // 2 - 1)
        self._add(y, max(0, (w - len(head)) // 2), head[:w], title)
        barw = max(10, min(48, w - 6))
        fill = max(0, min(barw, int(frame.progress * barw)))
        bx = max(0, (w - barw) // 2)
        self._add(y + 2, bx, '█' * fill, self.pal.get('accent') | curses.A_BOLD)
        self._add(y + 2, bx + fill, '░' * (barw - fill), self.pal.get('dim'))
        return frame.done


register_splash(BrailleBarSplash, builtin=True)


def run_splash(scr, pal, provider_cls, *, is_done, frac, counts, label, deadline=None, seed=None,
               linger=False, fps_cap=None):
    '''Drive a Splash provider's frame loop until inspection is done AND the animation is at rest
    (or a hard `deadline`). The provider only draws one frame from a SplashFrame; the HOST owns the
    clock, the skip key, and the plain-text fallback: a keypress CANCELS the animation but a plain
    progress line keeps updating on a clean screen until inspection actually finishes, so dropping
    the eye-candy never hides the real state. `frac()`/`counts()`/`is_done()` are polled each frame;
    dt-based timing means a slow frame just eases further, never desyncs. Never raises for a
    misbehaving provider frame — a broken render falls back to the text line.

    `linger`: don't auto-exit when inspection is done — keep the animation running (progress pinned
    at 1.0) until the user presses a key, which then ends it. For enjoying a splash when a fast load
    would otherwise whisk it away.'''
    h, w = scr.getmaxyx()
    provider = provider_cls(scr, pal, (h, w), seed)
    fps = getattr(provider_cls, 'fps', 30.0) or 30.0
    if fps_cap:                                       # reduced motion (e.g. SSH): a calmer frame rate
        fps = min(fps, fps_cap)
    frame_dt = 1.0 / fps
    min_dur = getattr(provider_cls, 'min_duration', MIN_DURATION)
    raw = bool(getattr(provider_cls, 'raw', False))   # provider paints truecolor to the tty itself
    scr.nodelay(True)
    used_raw = False
    if raw:
        _tty_write('\033[?25l\033[2J')                # hide cursor, clear once; frames repaint in place
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
                    if raw:
                        used_raw = True
                        _tty_write(_sgr_downconvert(provider.render(frame) or '', pal))
                        at_rest = bool(getattr(provider, 'at_rest', done))
                    else:
                        at_rest = bool(provider.render(frame))
                except Exception:                     # noqa: BLE001 — a broken splash never bricks startup
                    animate = False
                    if used_raw:
                        _tty_write('\033[0m')
                        scr.clearok(True)
                    _draw_progress_text(scr, pal, label, frame.counts, h, w)
                if animate and scr.getch() != -1:     # a key: end the show (linger) or drop to text
                    if linger:
                        return                        # linger: watch as long as you like, any key exits
                    animate = False
                    if used_raw:
                        _tty_write('\033[0m')
                        scr.clearok(True)
            else:
                _draw_progress_text(scr, pal, label, frame.counts, h, w)
            if not (raw and animate):                 # raw frames own the tty; skip curses' repaint
                scr.noutrefresh()
                curses.doupdate()
            if deadline is not None and now >= deadline:
                return
            if animate:
                if not linger and done and at_rest and (now - start) >= min_dur:
                    return                            # (linger: keep animating until a keypress above)
            elif done:                                # text mode: leave as soon as it's finished
                return
            slack = frame_dt - (time.monotonic() - now)
            if slack > 0:
                time.sleep(slack)
    finally:
        scr.nodelay(False)
        if used_raw:
            _tty_write('\033[0m\033[?25h')            # reset colours, restore the cursor
            scr.clearok(True)                         # force the next curses refresh to wipe the raw frame
