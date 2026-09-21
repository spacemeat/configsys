'''In-TUI issue filing (report / request / suggest-OS): the review-and-send overlay and the flow
builder, driven with a fake stdscr (scripted getch, BufferSurface grid) so the render + consent path
is tested deterministically without curses/pty. The send itself is stubbed — no network.'''

from _render_harness import RecordingPalette, build_ctx
from configsys.tui import menu
from configsys.tui.surface import BufferSurface

import curses
import pytest


class _Scr(BufferSurface):
    '''A BufferSurface that also answers getch() from a scripted key list (Esc when exhausted).'''
    def __init__(self, keys, h=40, w=140):
        super().__init__(h, w)
        self._keys = list(keys)

    def getch(self):
        return self._keys.pop(0) if self._keys else 27

    def timeout(self, *a):
        pass

    def keypad(self, *a):
        pass


@pytest.fixture(scope='module')
def ctx(tmp_path_factory):
    return build_ctx(tmp_path_factory.mktemp('issue'))


# -- the review overlay renders the exact body and honours cancel -------------

def test_review_shows_full_body_and_cancels():
    scr = _Scr([27])                                   # Esc immediately
    body = 'line one\nZZ_PII_CANARY_ZZ\n### What works / what broke'
    note = menu._report_review(scr, RecordingPalette(), None,
                               '[os-request] add solus', body, 'os-request', 'last-os-request.md')
    assert note == 'issue not sent'
    text = ' '.join(scr.text_rows())
    assert 'review issue' in text and 'add solus' in text        # header + title
    assert 'ZZ_PII_CANARY_ZZ' in text                            # the FULL body is shown for review
    assert 'SEND to' in text and 'Esc cancel' in text            # the consent footer


# -- pressing s files it (send stubbed) and reports the outcome ---------------

def test_review_send_reports_filed_url(monkeypatch):
    monkeypatch.setattr('configsys.app._file_issue',
                        lambda *a, **k: (0, ['configsys: filed — https://github.com/x/issues/7']))
    scr = _Scr([ord('s'), ord(' ')])                   # send, then any key to return
    note = menu._report_review(scr, RecordingPalette(), None, 'T', 'b', 'os-request', 'last.md')
    assert note == 'issue filed: https://github.com/x/issues/7'


def test_review_send_no_gh_points_to_saved_body(monkeypatch, tmp_path):
    import types
    monkeypatch.setattr('configsys.app._file_issue',
                        lambda *a, **k: (0, ['configsys: no `gh` …', '  https://github.com/x/issues/new?…']))
    scr = _Scr([ord('s'), ord(' ')])
    stub_ctx = types.SimpleNamespace(paths=types.SimpleNamespace(state_dir=tmp_path))
    note = menu._report_review(scr, RecordingPalette(), stub_ctx, 'T', 'b', 'os-request', 'last-os.md')
    assert 'not auto-filed' in note and 'last-os.md' in note


# -- the os-request flow builds a real payload end-to-end (render, no send) ----

def test_issue_flow_os_builds_and_reviews(ctx):
    scr = _Scr([27])                                   # os kind needs no name prompt -> straight to review, Esc
    note = menu._issue_flow(scr, RecordingPalette(), ctx, 'os')
    assert note == 'issue not sent'
    text = ' '.join(scr.text_rows())
    assert '[os-request]' in text                       # the generated title rendered
    assert 'configsys block' in text                    # the detected-OS section
    assert 'os-release' in text                          # the scrubbed os-release block


def test_issue_flow_report_no_failure_returns_note(ctx, monkeypatch):
    # blank name + no captured failures -> a clear note, no overlay
    monkeypatch.setattr(menu, '_input_box', lambda *a, **k: '')     # user submits an empty name
    monkeypatch.setattr('configsys.reportgen.load_failures', lambda _p: [])
    note = menu._issue_flow(_Scr([]), RecordingPalette(), ctx, 'report')
    assert 'nothing to report' in note


def test_issue_flow_cancel_at_prompt_returns_none(ctx, monkeypatch):
    monkeypatch.setattr(menu, '_input_box', lambda *a, **k: None)   # user Escs the name prompt
    assert menu._issue_flow(_Scr([]), RecordingPalette(), ctx, 'request') is None
