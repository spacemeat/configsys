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
                                   {'NO_COLOR': '1'}])
def test_caps_keep_term(extra):
    env = {'TERM': 'xterm-256color', 'COLORTERM': 'truecolor', **extra}
    assert screen.direct_color_term(env) is None


def test_already_direct_or_gnu_screen_keeps_term():
    assert screen.direct_color_term({'TERM': 'xterm-direct', 'COLORTERM': 'truecolor'}) is None
    assert screen.direct_color_term({'TERM': 'screen-256color', 'COLORTERM': 'truecolor'}) is None


def test_tmux_goes_direct():
    # tmux downconverts RGB itself for an outer terminal that can't show it, so direct is safe there
    env = {'TERM': 'tmux-256color', 'COLORTERM': 'truecolor', 'TMUX': '/tmp/tmux-1000/default,1,0'}
    assert screen.direct_color_term(env) == 'tmux-direct'
    env = {'TERM': 'screen-256color', 'COLORTERM': 'truecolor', 'TMUX': '/tmp/tmux-1000/default,1,0'}
    assert screen.direct_color_term(env) == 'screen-direct'    # tmux with an old screen-* TERM


@pytest.mark.parametrize('env', [
    {'TERM': 'xterm-kitty'},                                  # TERM survives SSH; COLORTERM doesn't
    {'TERM': 'alacritty'},
    {'TERM': 'xterm-ghostty'},
    {'TERM': 'xterm-256color', 'LC_TERMINAL': 'iTerm2'},      # forwarded by the default SendEnv LC_*
    {'TERM': 'xterm-256color', 'TERM_PROGRAM': 'WezTerm'},
    {'TERM': 'xterm-256color', 'WT_SESSION': 'abc'},
    {'TERM': 'xterm-256color', 'VTE_VERSION': '7600'},
])
def test_truecolor_signals_without_colorterm(env):
    assert screen.direct_color_term(env) is not None


@pytest.mark.parametrize('env', [
    {'TERM': 'xterm-256color', 'VTE_VERSION': '5000'},        # VTE before colon-form SGR
    {'TERM': 'xterm-256color', 'TERM_PROGRAM': 'Apple_Terminal'},
    {'TERM': 'linux'},
])
def test_no_truecolor_signal_keeps_term(env):
    assert screen.direct_color_term(env) is None


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


def test_build_resolves_a_terminal_private_entry(monkeypatch, tmp_path):
    # kitty ships xterm-kitty in its own dir and points TERMINFO at it; tic must see that to resolve
    # `use=xterm-kitty`, or the build fails and kitty silently falls back to palette redefinition.
    import os
    import shutil
    import subprocess
    monkeypatch.undo()
    if not shutil.which('tic') or not shutil.which('infocmp'):
        pytest.skip('needs tic + infocmp')
    private = tmp_path / 'kitty-terminfo'
    src = subprocess.run(['infocmp', '-x', 'xterm-256color'], capture_output=True, text=True).stdout
    src = src[src.index('xterm-256color|'):].replace('xterm-256color|', 'xterm-fakekitty|', 1)
    (tmp_path / 'fk.src').write_text(src)
    subprocess.run(['tic', '-x', '-o', str(private), str(tmp_path / 'fk.src')], check=True)
    monkeypatch.setattr(screen.curses, 'has_extended_color_support', lambda: True, raising=False)
    env = {'TERM': 'xterm-fakekitty', 'CONFIGSYS_COLOR': '24bit', 'TERMINFO': str(private),
           'XDG_CACHE_HOME': str(tmp_path / 'cache'), 'PATH': os.environ.get('PATH', '')}
    assert screen.direct_color_setup(env) == ('xterm-fakekitty-direct',
                                              str(tmp_path / 'cache' / 'configsys' / 'terminfo'))
