'''review-2026-11-2 B11: one parse chokepoint for config files (a `{}` file loads), one bool dialect for
every setting (a typo is the default + a warning, never the opposite), `config set` refuses a bad
value, and `check` reports a skipped layer and an unknown pick instead of saying 0 errors.'''

import pytest

from configsys import actions, app, layers


def _cs(home, *argv):
    return app.main(['--home', str(home), '--os', 'pop_os!:24.04', *argv])


def _top(home):
    return home / '.config' / 'configsys' / 'configsys.hu'


@pytest.mark.parametrize('text', ['{}', '{ }', '{\n}\n', '', '  \n'])
def test_tiny_and_blank_files_load(tmp_path, text):
    f = tmp_path / 'x.hu'
    f.write_text(text)
    _trove, data = layers.read_tree(f)
    assert data == {}
    assert layers.read_setting(f, 'scope') is None


def test_a_tiny_top_config_does_not_brick(tmp_path, capsys):
    _top(tmp_path).parent.mkdir(parents=True)
    _top(tmp_path).write_text('{}\n')
    assert _cs(tmp_path, 'config', 'get', 'scope') == 0


@pytest.mark.parametrize('token, default, want', [
    ('true', False, True), ('YES', False, True), ('on', False, True), ('1', False, True),
    ('false', True, False), ('Off', True, False), ('0', True, False),
    ('ture', True, True), ('ture', False, False), ('enabled', True, True), (None, True, True),
    (True, False, True), (False, True, False)])
def test_parse_bool_unknown_is_the_default(token, default, want):
    assert layers.parse_bool(token, default) is want


def test_bool_settings_registry_matches_config_settings():
    assert layers.BOOL_SETTINGS == {k for k, v in actions.CONFIG_SETTINGS.items() if v[0] == 'bool'}


def test_a_typo_never_flips_a_default_on_setting(tmp_path):
    from configsys.config import Config
    from configsys.paths import Paths
    _top(tmp_path).parent.mkdir(parents=True)
    _top(tmp_path).write_text('{ reboot-advice: ture  adopt-installed: ture  auto-tighten: ture\n'
                              '  installer-shell-writes: no  scope: sytem }\n')
    paths = Paths(env={'HOME': str(tmp_path)})
    cfg = Config.load(paths)
    assert cfg.reboot_advice() is True and cfg.adopt_installed() is True
    assert cfg.auto_tighten() is False
    assert cfg.block_installer_shell_writes() is True          # only `allow` turns the guard off
    assert cfg.default_scope() is None                          # `sytem` = the default (user)
    warns = '\n'.join(layers.setting_value_warnings(cfg._layers))
    for key in ('reboot-advice', 'adopt-installed', 'auto-tighten', 'installer-shell-writes', 'scope'):
        assert f'`{key}:' in warns


@pytest.mark.parametrize('key, value', [('reboot-advice', 'ture'), ('scope', 'sytem'),
                                        ('installer-shell-writes', 'alow'),
                                        ('dirs.user', 'relative/dir')])
def test_config_set_refuses_a_bad_value(tmp_path, capsys, key, value):
    assert _cs(tmp_path, 'config', 'set', key, value) != 0
    assert value not in (_top(tmp_path).read_text() if _top(tmp_path).exists() else '')


def test_config_set_accepts_good_values(tmp_path):
    assert _cs(tmp_path, 'config', 'set', 'reboot-advice', 'off') == 0
    assert _cs(tmp_path, 'config', 'set', 'scope', 'system') == 0
    assert _cs(tmp_path, 'config', 'set', 'dirs.app', 'apps2') == 0     # category dirs stay relative
    text = _top(tmp_path).read_text()
    assert 'reboot-advice: false' in text and 'scope: system' in text


def test_check_reports_an_unknown_pick_and_warns_on_picks_add(tmp_path, capsys):
    assert _cs(tmp_path, 'picks', 'add', 'nosuchtool') == 0
    assert 'not a known component' in capsys.readouterr().err
    assert _cs(tmp_path, 'check') == 1
    out = capsys.readouterr().out
    assert "picks: 'nosuchtool' (this machine" in out


def test_check_reports_an_unreadable_primary(tmp_path, capsys):
    # a skipped (malformed) primary data file is an error, as on the `!` page — not "0 error(s)"
    from configsys import plugins
    cfgdir = _top(tmp_path).parent
    prim = cfgdir / 'plugins' / 'mine'
    prim.mkdir(parents=True)
    (prim / 'plugin.hu').write_text(f'{{ name: mine  requires-abi: {plugins.ABI_VERSION}  data: [ mine.hu ] }}\n')
    (prim / 'mine.hu').write_text('{ picks: { this-machine: [ btop \n')
    _top(tmp_path).write_text('{ plugins: [ { source: mine  primary: true } ] }\n')
    rc = _cs(tmp_path, 'check')
    out = capsys.readouterr().out
    assert rc != 0
    assert 'ERROR   skipped' in out and 'mine.hu' in out


def test_shipped_layer_files_hold_no_key_twice():
    # B17 / primary-04: the repo's own layers (not re-parsed per load) are held to it here
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for name in ('routes.hu', 'config.hu'):
        assert layers.duplicate_keys_in_text((root / name).read_text(encoding='utf-8')) == [], name


def test_a_key_set_twice_is_a_check_warning(tmp_path, capsys):
    _top(tmp_path).parent.mkdir(parents=True)
    _top(tmp_path).write_text('{ splash: ocean  picks: { this-machine: [ btop ] }  splash: plain }\n')
    _cs(tmp_path, 'check')
    assert '`splash` set twice' in capsys.readouterr().out


def test_check_lints_reach_the_issues_page(tmp_path):
    # G2: `check`-only findings (here a key set twice) join diagnostics once the background pass lands
    from configsys.app import Context, build_parser
    _top(tmp_path).parent.mkdir(parents=True)
    _top(tmp_path).write_text('{ splash: ocean  splash: plain }\n')
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop_os!:24.04', 'inspect']))
    ctx.start_check_lints()
    ctx._check_thread.join(60)
    texts = [d['text'] for d in ctx.diagnostics()]
    assert sum('`splash` set twice' in x for x in texts) == 1      # once, not doubled


def test_theme_lint_flags_and_theme_set_refuses_what_the_tui_ignores(tmp_path, capsys):
    # G6 / tui-theme-15
    from configsys.tui.theme import theme_problems, parse_color
    assert parse_color('#-1-1-1') is None
    bad = theme_problems({'colors': {'accent': '#12345'},
                          'pages': {'profile': {}, 'components': {'componnet': {'fg': 'red'},
                                                                  'component': {'fg': 'reddish', 'blink': True}}}})
    keys = {k for k, _w in bad}
    assert keys == {'colors.accent', 'pages.profile', 'pages.components.componnet',
                    'pages.components.component.fg', 'pages.components.component.blink'}
    assert _cs(tmp_path, 'theme', 'set', 'pages.components.componnet.fg', 'red') == 1
    assert _cs(tmp_path, 'theme', 'set', 'pages.components.component.fg', 'accent') == 0


def test_search_and_version(tmp_path, capsys):
    # G6 / parity-18, app-cli-33
    assert _cs(tmp_path, 'search', 'terminal', 'emulator') == 0
    assert 'kitty' in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        app.main(['--version'])
    assert e.value.code == 0 and capsys.readouterr().out.startswith('configsys ')
