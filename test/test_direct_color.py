'''direct_color_term(): when a truecolor terminal (COLORTERM) runs under a -256color TERM, curses is
started against the `-direct` terminfo so colors go out as real 24-bit SGR, not OSC 4 palette
redefinitions a terminal may ignore (COSMIC's terminal: every color came out wrong).'''

import pytest

from configsys.tui import screen


@pytest.fixture(autouse=True)
def _all_entries_exist(monkeypatch):
    monkeypatch.setattr(screen, '_terminfo_exists', lambda name, env, system=True: True)
    monkeypatch.setattr(screen.curses, 'has_extended_color_support', lambda: True, raising=False)


def test_truecolor_xterm_goes_direct():
    assert screen.direct_color_term({'TERM': 'xterm-256color', 'COLORTERM': 'truecolor'}) == 'xterm-direct'
    assert screen.direct_color_term({'TERM': 'foot', 'COLORTERM': '24bit'}) == 'foot-direct'


def test_no_colorterm_keeps_term():
    assert screen.direct_color_term({'TERM': 'xterm-256color'}) is None


def test_explicit_24bit_forces_direct_without_colorterm():
    assert screen.direct_color_term({'TERM': 'xterm-256color', 'CONFIGSYS_COLOR': '24bit'}) == 'xterm-direct'


@pytest.mark.parametrize('extra', [{'CONFIGSYS_COLOR': '256'}, {'CONFIGSYS_COLOR': '16'},
                                   {'NO_COLOR': '1'}, {'TMUX': '/tmp/tmux'}])
def test_caps_and_multiplexers_keep_term(extra):
    env = {'TERM': 'xterm-256color', 'COLORTERM': 'truecolor', **extra}
    assert screen.direct_color_term(env) is None


def test_already_direct_or_multiplexer_term():
    assert screen.direct_color_term({'TERM': 'xterm-direct', 'COLORTERM': 'truecolor'}) is None
    assert screen.direct_color_term({'TERM': 'tmux-256color', 'COLORTERM': 'truecolor'}) is None


def test_missing_direct_entry_and_no_tic_keeps_term(monkeypatch):
    monkeypatch.setattr(screen, '_terminfo_exists', lambda name, env, system=True: False)
    monkeypatch.setattr('shutil.which', lambda _: None)
    assert screen.direct_color_term({'TERM': 'xterm-256color', 'COLORTERM': 'truecolor'}) is None


def test_missing_direct_entry_is_built_into_cache(monkeypatch, tmp_path):
    # A fresh Debian/Ubuntu/Pop has only ncurses-base (no *-direct entries, which live in
    # ncurses-term): build xterm-direct = xterm-256color + the direct overlay with tic, in the cache.
    import os
    import shutil
    monkeypatch.undo()                                # the real _terminfo_exists from here on
    if not shutil.which('tic') or not screen._terminfo_exists('xterm-256color', {}):
        pytest.skip('needs tic + an xterm-256color entry')
    monkeypatch.setattr(screen.curses, 'has_extended_color_support', lambda: True, raising=False)
    monkeypatch.setattr(screen, '_TERMINFO_DIRS', ())   # hide any system *-direct entries
    env = {'TERM': 'xterm-256color', 'COLORTERM': 'truecolor', 'XDG_CACHE_HOME': str(tmp_path),
           'PATH': os.environ.get('PATH', '')}
    name, tdir = screen.direct_color_setup(env)
    assert name == 'xterm-direct' and tdir == str(tmp_path / 'configsys' / 'terminfo')
    assert (tmp_path / 'configsys' / 'terminfo' / 'x' / 'xterm-direct').is_file()
    assert screen.direct_color_setup(env) == (name, tdir)          # reused, not rebuilt
