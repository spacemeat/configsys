'''startup.py — the startup inspection worker, the splash choice and the effects level.

Split out of menu.py (review-2026-11-2 D2).
'''

import threading
import time


SPLASH_THRESHOLD = 0.25    # only show the splash if inspection is still going after this (seconds)


def _is_ssh(env):
    '''Heuristic: are we on a remote (SSH) session? Imperfect — mosh doesn't set these, and tmux /
    screen often STRIP them — so it only feeds the effects DEFAULT, never a hard gate.'''
    return any(env.get(k) for k in ('SSH_CONNECTION', 'SSH_TTY', 'SSH_CLIENT'))


is_ssh = _is_ssh                         # the public spelling (`configsys --probe` reads it)


def resolve_effects(ctx):
    '''Canonicalize the TUI motion level to 'full'|'reduced'|'none' and stamp CONFIGSYS_EFFECTS, so the
    Palette (gradient) and the splash both read one value. Priority: --effects (already in the env) >
    the `effects:` machine setting > an auto-default of reduced over SSH, else full. Call at TUI start,
    before the first Palette / the splash choice.'''
    import os
    from .theme import env_effects
    lvl = env_effects() or ctx.config.effects() or ('reduced' if _is_ssh(ctx.env) else 'full')
    os.environ['CONFIGSYS_EFFECTS'] = lvl
    return lvl


def _chosen_splash(ctx):
    '''(enabled, name): whether the startup splash is ALLOWED (independent of the "is there work"
    timing gate) and which provider was chosen — the `splash:` machine setting's value, or None for
    the built-in default. On/off follows the one override rule, CLI > env > config > default:
    --splash-linger (Context drops CONFIGSYS_NO_SPLASH for the run) > CONFIGSYS_NO_SPLASH >
    CONFIGSYS_SPLASH=always|linger (shows the built-in over a `splash: off`) > a `splash: off` setting
    or the legacy `theme: { splash: false }` opt-out > on. Verbose logging is off regardless (they
    want the text log). TTY is guaranteed by cli.ops.cmd_tui. Whether a NAMED provider is actually
    registered is resolved at construction time.'''
    from .. import report
    from .theme import env_color_cap, env_effects, is_off
    if ctx.env.get('CONFIGSYS_NO_SPLASH'):
        return False, None
    if ctx.reporter.level >= report.VERBOSE:
        return False, None
    v = ctx.config.splash()
    if (isinstance(v, str) and is_off(v)) or \
            (v is None and is_off((ctx.config.theme() or {}).get('splash'))):   # legacy theme opt-out
        if not _splash_forced(ctx):                  # the env's always/linger beats the setting
            return False, None
        v = None                                     # ... and shows the built-in
    if env_effects() == 'none' or env_color_cap() == 'none':   # minimal/mono: a progress bar is
        return True, None                                      # feedback, not eye-candy — keep it,
                                                               # but force the plain built-in (no
                                                               # fancy plugin splash, no gradient)
    name = None if (v is None or v.lower() in ('true', 'default', 'on')) else v
    if name is not None:                             # accept a plugin name as an alias for its splash
        from .. import plugins
        decls = plugins.effective_declared(ctx.paths.user_config_file, ctx.paths.plugins_dir)
        name = plugins.resolve_splash_value(name, ctx.paths.plugins_dir, decls)
    return True, name


def _splash_forced(ctx):
    '''`CONFIGSYS_SPLASH=always` (or `--splash-linger`) bypasses the "only when there's work" timing
    gate — the splash shows even on a fast/warm run (to preview it, or just enjoy it) and over a
    `splash: off` setting. An exported CONFIGSYS_NO_SPLASH still wins over the variable, not the flag.'''
    return ctx.env.get('CONFIGSYS_SPLASH', '').lower() in ('always', 'force', '1', 'linger', 'hold')


def _splash_linger(ctx):
    '''`--splash-linger` / `CONFIGSYS_SPLASH=linger`: keep the splash animating AFTER inspection is
    done, until a key is pressed — so a too-fast load doesn't rob you of the show.'''
    return ctx.env.get('CONFIGSYS_SPLASH', '').lower() in ('linger', 'hold')


# Startup progress is ONE bar over the real phases: HEAD (load/route/resolve), DETECT (detect_pins),
# BATCH (the inspect prepass — a second package scan), INSPECT (per-unit). Each phase gets a band whose
# WIDTH is its learned share of the total time (startuptiming), and within its band the bar is paced by
# ELAPSED TIME toward that learned duration — so it advances at a roughly constant rate instead of
# lurching with the front-loaded per-driver counts. Real ticks mark where a phase actually STARTS (so
# the next band begins) and, on completion, feed next run's estimate. See startuptiming.py.
_PACE_CAP = 0.985       # a time-paced band creeps to at most this of its width, then waits for the real
                        # phase end (the next phase's first tick) to snap it forward — no false 100%.


class _InspectWorker:
    '''Runs load_pipeline on a background thread so the main thread can animate the splash while
    inspection proceeds. Exposes a live 0..1 progress fraction, a done flag, and re-raises any
    exception from the worker on join (so load errors still surface normally).'''

    def __init__(self, ctx):
        from .. import startuptiming
        self.ctx = ctx
        self._i = 0
        self._total = 0                      # INSPECT: per-unit progress (kept for phase_label + counts)
        self._pre_n = 0                      # DETECT active once >0
        self._bat_n = 0                      # BATCH active once >0
        self._start = time.monotonic()
        self._done = threading.Event()
        self._result = None
        self._exc = None
        # learned per-phase durations -> band WIDTHS proportional to time share. A phase that won't run
        # this session (detection is skipped when adopt-installed is off / under --pretend) gets width 0
        # so the bar doesn't reserve dead space for it.
        est = startuptiming.load(ctx.paths)
        if not (ctx.config.adopt_installed() and not ctx.runner.pretend):
            est['detect'] = 0.0
        self._est = est
        tot = max(startuptiming.MIN, sum(est[p] for p in startuptiming.PHASES))
        self._band = {}                      # phase -> (lo, hi) cumulative fractions
        acc = 0.0
        for p in startuptiming.PHASES:
            lo = acc / tot
            acc += est[p]
            self._band[p] = (lo, acc / tot)
        self._t = {'head': self._start, 'detect': None, 'batch': None, 'inspect': None}
        self._thread = threading.Thread(target=self._work, daemon=True)

    def _phase_start(self, phase):
        if self._t[phase] is None:
            self._t[phase] = time.monotonic()

    def _sink(self, i, total, *rest):
        self._phase_start('inspect')
        self._i, self._total = i, total

    def _detect_sink(self, done, total):
        self._phase_start('detect')
        self._pre_n = total

    def _batch_sink(self, done, total):
        self._phase_start('batch')
        self._bat_n = total

    def _work(self):
        try:
            self._result = self.ctx.load_pipeline(progress=self._sink, detect_progress=self._detect_sink,
                                                  batch_progress=self._batch_sink)
            self._record_timing()
        except BaseException as e:          # captured, re-raised on the main thread in join()
            self._exc = e
        finally:
            self._done.set()

    def _record_timing(self):
        '''Fold this run's actual phase durations into the learned estimate (EMA). A phase's duration
        runs from its start to the next STARTED phase's start (or, for the last, to now) — so a skipped
        phase is simply absent and its predecessor absorbs the gap.'''
        from .. import startuptiming
        end = time.monotonic()
        started = [p for p in startuptiming.PHASES if self._t[p] is not None]
        measured = {}
        for i, p in enumerate(started):
            nxt = self._t[started[i + 1]] if i + 1 < len(started) else end
            measured[p] = nxt - self._t[p]
        if not getattr(self.ctx.runner, 'pretend', False):   # a dry run's empty probes would skew the pacing
            startuptiming.update(self.ctx.paths, measured)

    def phase_label(self):
        '''What the worker is doing right now — so the splash label tracks the phase, not a fixed
        string. (Read live by run_splash each frame.)'''
        if self._total:
            return 'checking install state'
        if self._bat_n:
            return 'reading package versions'
        if self._pre_n:
            return 'scanning installed packages'
        return 'loading configuration'

    def start(self):
        self._thread.start()
        return self

    def wait_settled(self, timeout):
        '''Block up to `timeout`; return True if inspection is STILL running (→ show the splash).'''
        return not self._done.wait(timeout)

    def _paced(self, phase):
        '''Time-pace the active phase's band: advance from its start proportional to elapsed/estimate,
        capped at _PACE_CAP of the band so it never shows a false 100% before the phase actually ends.'''
        lo, hi = self._band[phase]
        f = min(_PACE_CAP, (time.monotonic() - self._t[phase]) / max(0.02, self._est[phase]))
        return lo + (hi - lo) * f

    def frac(self):
        # the furthest phase that has STARTED (phases run in order); each band is paced by time toward
        # its learned duration, so the bar advances at a ~constant rate through the front-loaded scans
        # instead of lurching with their per-driver counts. Earlier bands are implicitly full (this
        # band's `lo` == the prior band's `hi`).
        for p in ('inspect', 'batch', 'detect'):
            if self._t[p] is not None:
                return self._paced(p)
        return self._paced('head')

    def counts(self):
        return (self._i, self._total)

    def done(self):
        return self._done.is_set()

    def join(self):
        self._done.wait()
        if self._exc is not None:
            raise self._exc
        return self._result
