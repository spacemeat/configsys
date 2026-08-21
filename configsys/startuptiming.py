'''startuptiming.py — a self-calibrating estimate of how long each startup phase takes, so the splash
bar can advance at a roughly CONSTANT rate (paced by TIME within each phase) rather than by item count.

Why not count? The two package-scan phases are wildly front-loaded: a scan of ~26 drivers finishes 21
of them in milliseconds (path/build drivers with nothing to enumerate), then waits 1-2s on a few slow
package-manager subprocesses (apt-cache policy over hundreds of packages, flatpak remote-ls). So
`done/total` lurches to ~80% instantly then crawls — the classic misleading progress bar. Pacing each
phase's band by elapsed time against a LEARNED duration is smooth; the real ticks just mark when a
phase actually ends (snap forward) and feed the next run's estimate. Stored as JSON in
<state>/startup-timing.json, EMA-folded each run so it converges to THIS machine's real timings.'''

import json

PHASES = ('head', 'detect', 'batch', 'inspect')
_DEFAULTS = {'head': 0.3, 'detect': 1.6, 'batch': 1.8, 'inspect': 1.6}   # rough first-run guess
_ALPHA = 0.4                    # EMA weight on the newest sample (converges over a few runs)
MIN = 0.05                      # floor: a near-zero phase can't collapse a band to nothing / div-by-0


def load(paths):
    '''The learned per-phase durations (seconds), falling back to defaults where unknown.'''
    out = dict(_DEFAULTS)
    try:
        data = json.loads(paths.startup_timing_file.read_text(encoding='utf-8'))
        for p in PHASES:
            v = data.get(p)
            if isinstance(v, (int, float)) and v > 0:
                out[p] = float(v)
    except (OSError, ValueError, AttributeError):
        pass
    return out


def update(paths, measured):
    '''EMA-fold this run's measured phase durations into the stored estimate. Best-effort — a write
    failure (or a phase that didn't run, absent from `measured`) is simply ignored.'''
    cur = load(paths)
    for p in PHASES:
        m = measured.get(p)
        if isinstance(m, (int, float)) and m >= 0:
            cur[p] = max(MIN, (1 - _ALPHA) * cur[p] + _ALPHA * m)
    try:
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        paths.startup_timing_file.write_text(json.dumps(cur, sort_keys=True), encoding='utf-8')
    except OSError:
        pass
