'''End-to-end-ish tests for the CLI entry, all in --pretend (no real mutation).'''

from configsys.app import main


def base_args(tmp_path):
    return ['--home', str(tmp_path), '--os', 'pop', '--pretend']


def test_inspect_generates_user_config_and_exits_zero(tmp_path, capsys):
    rc = main(base_args(tmp_path) + ['inspect'])
    assert rc == 0
    assert (tmp_path / '.config' / 'configsys' / 'configsys.hu').exists()   # XDG location
    out = capsys.readouterr().out
    assert 'OS: pop_os!' in out
    # the generated template leaves `configs:` commented, so the active set defaults to the
    # repo config.hu's configs (a `primary` plugin or this file can override it).
    assert 'profiles:' in out and 'dev' in out


def test_legacy_user_config_is_migrated(tmp_path, capsys):
    # an old ~/configsys.hu is moved to ~/.config/configsys/configsys.hu on first run
    legacy = tmp_path / 'configsys.hu'
    legacy.write_text('{ configs: [ mine ]  profiles: { mine: [ btop ] } }')
    rc = main(base_args(tmp_path) + ['inspect'])
    assert rc == 0
    new = tmp_path / '.config' / 'configsys' / 'configsys.hu'
    assert new.exists() and not legacy.exists()          # moved
    out = capsys.readouterr().out
    assert 'moved' in out and 'profiles: mine' in out     # migrated + its config in effect


def test_discover_false_in_user_config_disables_discovery(tmp_path, capsys, monkeypatch):
    cfgdir = tmp_path / '.config' / 'configsys'
    cfgdir.mkdir(parents=True)
    (cfgdir / 'configsys.hu').write_text('{ configs: [ ]  discover: false }')
    proj = tmp_path / 'proj'
    proj.mkdir()
    (proj / '.configsys.hu').write_text('{ profiles: { app-run: [ btop ] } }')
    monkeypatch.setenv('CONFIGSYS_CWD', str(proj))
    rc = main(base_args(tmp_path) + ['inspect'])
    assert rc == 0
    assert 'app-run' not in capsys.readouterr().out       # discovery disabled by config


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
    (tmp_path / 'configsys.hu').write_text('{ components: { firefox: {} } }')
    rc = main(base_args(tmp_path) + ['where', 'firefox'])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'removes' in out and 'nothing (removed)' in out


def test_where_unknown_component_exits_one(tmp_path, capsys):
    rc = main(base_args(tmp_path) + ['where', 'no-such-thing'])
    assert rc == 1
    assert 'unknown component' in capsys.readouterr().out


def test_check_clean_config_is_ok(tmp_path, capsys):
    rc = main(base_args(tmp_path) + ['check'])
    assert rc == 0
    assert 'no issues' in capsys.readouterr().out


def test_check_reports_errors_and_warnings_with_exit_code(tmp_path, capsys):
    (tmp_path / 'configsys.hu').write_text('''{
        configs: [ mine ]
        profiles: { mine: [ btop, ghosttool ] }
        components: {
            bad-via: { install: [ { via: zypper } ] }
            bad-req: { install: [ { via: native  requires: nope } ] }
        }
    }''')
    rc = main(base_args(tmp_path) + ['check'])
    out = capsys.readouterr().out
    assert rc == 1                                   # has errors
    assert "via:'zypper' is not a known driver" in out
    assert "profile 'mine': unknown component 'ghosttool'" in out
    assert 'warn' in out and "requires 'nope'" in out
    assert '.config/configsys/configsys.hu' in out   # attributed to the user file (XDG path)


def test_where_shows_active_pin(tmp_path, capsys):
    (tmp_path / 'configsys.hu').write_text('{ pins: { steam: flatpak } }')
    rc = main(base_args(tmp_path) + ['where', 'steam'])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'pinned' in out and 'via:flatpak' in out
    assert 'flatpak\\steam' in out                   # the pin actually reroutes it


def test_pretend_install_honors_binding_pin(tmp_path, capsys):
    (tmp_path / 'configsys.hu').write_text('{ pins: { steam: flatpak } }')
    rc = main(base_args(tmp_path) + ['install', 'steam'])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'sudo flatpak install --system -y flathub com.valvesoftware.Steam' in out


def test_check_flags_bogus_pin(tmp_path, capsys):
    (tmp_path / 'configsys.hu').write_text('{ pins: { steam: snapp } }')
    rc = main(base_args(tmp_path) + ['check'])
    assert rc == 1
    assert "pin 'steam: snapp'" in capsys.readouterr().out


def test_cli_discovers_project_and_auto_activates(tmp_path, capsys, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    proj = tmp_path / 'proj'
    (proj / 'src').mkdir(parents=True)
    (proj / '.configsys.hu').write_text('{ profiles: { app-run: [ btop ] } }')
    monkeypatch.setenv('CONFIGSYS_CWD', str(proj / 'src'))       # run "from" a project subdir
    rc = main(['--home', str(home), '--os', 'pop', '--pretend', 'inspect'])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'app-run' in out and 'project:' in out and '.configsys.hu' in out


def test_cli_no_discover_kill_switch(tmp_path, capsys, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    proj = tmp_path / 'proj'
    proj.mkdir()
    (proj / '.configsys.hu').write_text('{ profiles: { app-run: [ btop ] } }')
    monkeypatch.setenv('CONFIGSYS_CWD', str(proj))
    monkeypatch.setenv('CONFIGSYS_NO_DISCOVER', '1')
    rc = main(['--home', str(home), '--os', 'pop', '--pretend', 'inspect'])
    assert rc == 0
    assert 'app-run' not in capsys.readouterr().out             # discovery disabled


def test_inspect_is_resilient_to_a_bad_active_component(tmp_path, capsys):
    # an active profile with an unroutable component -> that one shows as an error,
    # the rest still inspect, exit 0 (you can always get past it)
    (tmp_path / 'configsys.hu').write_text(
        '{ configs: [ mine ]  profiles: { mine: [ btop, ghost-tool ] } }')
    rc = main(base_args(tmp_path) + ['inspect'])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'apt\\btop' in out                     # good component still resolved + shown
    assert 'unresolved' in out and 'ghost-tool' in out
