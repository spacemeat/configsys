'''Headless tests for pure TUI helpers (no curses). Screen-behavior tests live in the pty
smoke checks; this covers the value-formatting logic that the Config screen relies on.'''

from configsys.tui.menu import _setting_str, _hex


def test_setting_str_scope_defaults_to_user():
    assert _setting_str('scalar', None, 'scope') == 'user (default)'
    assert _setting_str('scalar', '', 'scope') == 'user (default)'
    assert _setting_str('scalar', 'system', 'scope') == 'system'


def test_setting_str_kinds():
    assert _setting_str('bool', True) == 'true'
    assert _setting_str('bool', False) == 'false'
    assert _setting_str('list', ['native', 'source']) == 'native source'
    assert _setting_str('list', []) == '(unset — built-in default)'
    assert _setting_str('scalar', None) == '(unset)'
    assert _setting_str('scalar', 'user') == 'user'


def test_hex_formatting():
    assert _hex((200, 140, 240)) == '#c88cf0'
    assert _hex((0, 0, 0)) == '#000000'
    assert _hex((255, 255, 255)) == '#ffffff'
