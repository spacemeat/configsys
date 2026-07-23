import io

from configsys.report import Reporter, SILENT, DEFAULT, VERBOSE, DEBUG


def rep(level):
    s = io.StringIO()               # not a tty -> transient status is suppressed
    return Reporter(level, stream=s), s


def test_silent_emits_nothing():
    r, s = rep(SILENT)
    r.error('boom'); r.event(VERBOSE, 'x'); r.status('y'); r.flush_transient()
    assert s.getvalue() == ''


def test_default_shows_errors_hides_verbose_events():
    r, s = rep(DEFAULT)
    r.error('boom'); r.event(VERBOSE, 'hidden')
    out = s.getvalue()
    assert 'boom' in out and 'hidden' not in out


def test_default_status_suppressed_off_tty():
    r, s = rep(DEFAULT)
    r.status('checking 1/10')       # StringIO isn't a tty -> nothing at DEFAULT
    assert s.getvalue() == ''


def test_verbose_shows_events_and_status_as_lines():
    r, s = rep(VERBOSE)
    r.event(VERBOSE, 'layer: repo'); r.status('checking 1/10')
    out = s.getvalue()
    assert 'layer: repo' in out and 'checking 1/10' in out


def test_debug_shows_both_verbose_and_debug():
    r, s = rep(DEBUG)
    r.event(VERBOSE, 'v-line'); r.event(DEBUG, 'd-line')
    out = s.getvalue()
    assert 'v-line' in out and 'd-line' in out


def test_pause_suppresses_resume_restores():
    r, s = rep(DEFAULT)
    r.pause(); r.error('while paused'); r.resume(); r.error('after resume')
    out = s.getvalue()
    assert 'while paused' not in out and 'after resume' in out
