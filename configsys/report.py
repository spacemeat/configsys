'''report.py — a verbosity-aware console reporter for the load/resolve/inspect path.

Streams progress + errors to stderr AS work happens, so long loads show motion and any
breakage surfaces on the console where the user launched configsys — while the TUI `!`
page still collects everything (this is additive, not a replacement). stderr keeps stdout
pipe-clean.

Verbosity ladder (Context.verbosity):
  -1 SILENT   nothing to the console at all (only the TUI `!` page)
   0 DEFAULT  lightweight transient progress + errors as they're found
   1 VERBOSE  + layer stack, component overrides, per-unit install-state + timing
   2 DEBUG    + full route/binding/why detail

Paused while curses owns the screen (the in-TUI reload after an execute must not draw to
stderr) — the pre-curses initial load and the post-endwin summary run live.
'''

import sys

SILENT, DEFAULT, VERBOSE, DEBUG = -1, 0, 1, 2

_CLEAR_LINE = '\r\x1b[K'   # carriage-return + erase-to-end-of-line (tty only)


class Reporter:
    def __init__(self, level=DEFAULT, stream=None):
        self.level = level
        self.stream = stream if stream is not None else sys.stderr
        self._paused = False
        self._transient = False   # an un-terminated \r progress line is on screen

    # -- state ------------------------------------------------------------

    @property
    def muted(self):
        return self.level <= SILENT or self._paused

    def pause(self):
        '''Suspend output (used while curses owns the terminal).'''
        self.flush_transient()
        self._paused = True

    def resume(self):
        self._paused = False

    def _tty(self):
        try:
            return self.stream.isatty()
        except (AttributeError, ValueError):
            return False

    # -- output -----------------------------------------------------------

    def _line(self, text):
        if self.muted:
            return
        self.flush_transient()
        print(text, file=self.stream)
        self.stream.flush()

    def error(self, text):
        '''An error found during load/resolve — shown at DEFAULT and up (never when SILENT).'''
        self._line(f'  ✗ {text}')

    def event(self, min_level, text):
        '''A detail line shown only at `min_level` or above (VERBOSE / DEBUG).'''
        if not self.muted and self.level >= min_level:
            self._line(text)

    def status(self, text):
        '''Progress: a transient, overwritten single line at DEFAULT (tty only); a normal
        line at VERBOSE+ (so the running log is scrollable/greppable).'''
        if self.muted:
            return
        if self.level >= VERBOSE:
            self._line(text)
        elif self._tty():
            print(f'{_CLEAR_LINE}{text}', end='', file=self.stream)
            self.stream.flush()
            self._transient = True

    def flush_transient(self):
        '''Clear a pending transient progress line before permanent output / on teardown.'''
        if self._transient and self._tty():
            print(_CLEAR_LINE, end='', file=self.stream)
            self.stream.flush()
        self._transient = False
