'''splash.py — the splash HOST loop + the built-in `plain` default.

configsys splashes are provider plugins (see configsys/splashes.py for the ABI). This module owns
the FRAME LOOP shared by every provider (`run_splash`): it constructs the chosen `Splash`, drives
it at its frame rate while feeding live progress, and owns the skip key, the deadline, and the safe
plain-text fallback. The only provider shipped in core is `plain` — a static centred progress line
(no animation, no trust) that is both the default when `splash:` is unset and the universal
fallback. Fancier splashes (e.g. the ASCII-water `liquid` fill) live in code plugins like
configsys-liquid.
'''

import curses
import time

from ..splashes import Splash, SplashFrame, register_splash

MIN_DURATION = 0.6         # if a splash is shown at all, play at least this long (no one-frame flash)
DEFAULT_SPLASH = 'plain'   # the built-in, trust-free default when `splash:` is unset


def _draw_progress_text(scr, pal, label, counts, h, w):
    '''The host's plain progress line — the `plain` splash's whole body, shown after a skip, and the
    safe fallback for any splash. A clean screen with a centred "<label>: i/total (pct%)" so
    cancelling an animation never hides the real state.'''
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


class TextSplash(Splash):
    '''The built-in default: a plain centred progress line, no animation. Trust-free and always
    available — the fallback any splash degrades to, and what ships until/unless a plugin provides
    something fancier. A minimal reference for the Splash ABI.'''
    name = DEFAULT_SPLASH
    min_duration = 0.0

    def render(self, frame):
        _draw_progress_text(self.scr, self.pal, frame.label, frame.counts, self.h, self.w)
        return frame.done


register_splash(TextSplash, builtin=True)


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
