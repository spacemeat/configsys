'''End-to-end-ish tests for the CLI entry, all in --pretend (no real mutation).'''

from configsys.app import main


def base_args(tmp_path):
    return ['--home', str(tmp_path), '--os', 'pop', '--pretend']


def test_inspect_generates_user_config_and_exits_zero(tmp_path, capsys):
    rc = main(base_args(tmp_path) + ['inspect'])
    assert rc == 0
    assert (tmp_path / 'configsys.hu').exists()
    out = capsys.readouterr().out
    assert 'OS: pop_os!' in out
    assert 'profiles: dev' in out


def test_pretend_install_emits_apt_command_without_executing(tmp_path, capsys):
    rc = main(base_args(tmp_path) + ['install', 'btop'])
    assert rc == 0
    out = capsys.readouterr().out
    assert '[pretend] sudo apt-get install -y btop' in out


def test_pretend_lock_emits_apt_mark(tmp_path, capsys):
    rc = main(base_args(tmp_path) + ['lock', 'btop'])
    assert rc == 0
    out = capsys.readouterr().out
    assert '[pretend] sudo apt-mark hold btop' in out


def test_default_command_is_tui_falls_back_to_inspect(tmp_path, capsys):
    # Non-interactive stdout (pytest capture) -> graceful fallback to inspect.
    rc = main(base_args(tmp_path))
    assert rc == 0
    out = capsys.readouterr().out
    assert 'not an interactive terminal' in out
    assert 'OS: pop_os!' in out


def test_where_repo_component(tmp_path, capsys):
    rc = main(base_args(tmp_path) + ['where', 'btop'])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'defined in  routes.hu' in out
    assert 'apt\\btop' in out                      # resolves to the native unit on Pop


def test_where_overridden_component_shows_provenance(tmp_path, capsys):
    (tmp_path / 'configsys.hu').write_text(
        '{ components: { steam: { install: [ { via: flatpak  hub: flathub '
        ' app: com.valvesoftware.Steam } ] } } }')
    rc = main(base_args(tmp_path) + ['where', 'steam'])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'overrides routes.hu' in out
    assert 'flatpak\\steam' in out and 'apt\\flatpak' in out


def test_where_removed_component(tmp_path, capsys):
    (tmp_path / 'configsys.hu').write_text('{ components: { apod: {} } }')
    rc = main(base_args(tmp_path) + ['where', 'apod'])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'removes' in out and 'nothing (removed)' in out


def test_where_unknown_component_exits_one(tmp_path, capsys):
    rc = main(base_args(tmp_path) + ['where', 'no-such-thing'])
    assert rc == 1
    assert 'unknown component' in capsys.readouterr().out
