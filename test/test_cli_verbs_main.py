'''review-2026-11-2 app-cli-15 — the verbs no test drove through `main`, each with an assertion on
what it prints and its exit code (read verbs on a sandbox home; `updates` under --pretend).'''

import pytest

from configsys.app import main


@pytest.fixture
def home(tmp_path):
    def cs(*argv):
        return main(['--home', str(tmp_path), '--os', 'pop', *argv])
    assert cs('machine', 'add', 'laptop') == 0
    assert cs('picks', 'add', 'ripgrep') == 0
    assert cs('disp', 'set', 'fzf', 'interesting') == 0
    assert cs('theme', 'set', 'colors.accent', '#ff0000') == 0
    assert cs('theme', 'save', 'reddish') == 0
    return cs


def _out(capsys):
    return capsys.readouterr().out


def test_profile_list_and_show(home, capsys):
    capsys.readouterr()
    assert home('profile', 'list') == 0
    assert 'finders' in _out(capsys)
    assert home('profile', 'show', 'finders') == 0
    out = _out(capsys)
    assert 'profile finders' in out and 'component  fd' in out
    assert home('profile', 'show', 'no-such-profile') != 0


def test_machine_list_and_show(home, capsys):
    capsys.readouterr()
    assert home('machine', 'list') == 0
    assert 'laptop' in _out(capsys)
    assert home('machine', 'show', 'this-machine') == 0
    assert 'ripgrep' in _out(capsys)


def test_theme_show_list_load(home, capsys):
    capsys.readouterr()
    assert home('theme', 'show') == 0
    assert 'ff0000' in _out(capsys).lower()
    assert home('theme', 'list') == 0
    assert 'reddish' in _out(capsys)
    assert home('theme', 'unset', 'colors.accent') == 0
    assert home('theme', 'load', 'reddish') == 0
    capsys.readouterr()
    home('theme', 'show')
    assert 'ff0000' in _out(capsys).lower()                     # the pack overlaid the user theme


def test_disp_list_and_get(home, capsys):
    capsys.readouterr()
    assert home('disp', 'list') == 0
    assert 'fzf' in _out(capsys)
    assert home('disp', 'get', 'fzf') == 0
    assert 'interesting' in _out(capsys)
    assert home('disp', 'get', 'ripgrep') == 0
    assert 'new' in _out(capsys)


def test_updates_under_pretend_lists_nothing_and_exits_zero(home, capsys):
    capsys.readouterr()
    assert home('--pretend', 'updates') == 0
    assert '[pretend]' in capsys.readouterr().out


def test_theme_set_refuses_a_key_the_tui_would_never_read(home, capsys):
    # `theme set accent …` used to be written as theme.accent — a section nothing reads
    assert home('theme', 'set', 'accent', '#00ff00') == 1
    assert 'no such theme section' in capsys.readouterr().err
