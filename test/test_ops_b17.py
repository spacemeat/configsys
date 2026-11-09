'''review-2026-11-2 B17 — plan/ops misc: sync outcomes judged by one predicate (update syncs before it
re-pins); a third-party plugin's manifest is never edited; layout settings drop the glue-locations
cache; theme edits land where they take effect; dotfiles_units reuses the pipeline's units.'''

import types

import pytest

from configsys import actions, plugins
from configsys.paths import Paths


@pytest.mark.parametrize('action, present, moved', [
    ('ok', True, True), ('cloned', True, True), ('updated', True, True), ('local', True, True),
    ('ahead', True, True), ('kept', True, False), ('diverged', True, False),
    ('failed (boom)', False, False), ('unsigned', False, False), ('locked', False, False)])
def test_sync_succeeded(action, present, moved):
    assert plugins.sync_succeeded(action) is present
    assert plugins.sync_succeeded(action, moved=True) is moved


def _ctx(tmp_path, top='{ }\n'):
    paths = Paths(env={'HOME': str(tmp_path)})
    paths.user_config_file.parent.mkdir(parents=True, exist_ok=True)
    paths.user_config_file.write_text(top)
    return types.SimpleNamespace(paths=paths, runner=types.SimpleNamespace(pretend=False),
                                 invalidate=lambda: None, invalidate_config=lambda: None,
                                 ensure_user_config=lambda: None)


def test_update_with_a_bad_ref_changes_nothing(tmp_path, monkeypatch):
    c = _ctx(tmp_path, '{ plugins: [ { source: "github:me/p"  ref: v1 } ] }\n')
    monkeypatch.setattr(actions, 'plugin_sync', lambda ctx, decls: [('p', 'failed (no such ref)')])
    ok, msg, _r = actions.plugin_update(c, 'github:me/p', ref='nosuchref')
    assert not ok and 'nothing changed' in msg
    assert plugins.declared(c.paths.user_config_file)[0]['ref'] == 'v1'


def test_a_transitive_plugin_owned_by_a_third_party_is_refused(tmp_path):
    c = _ctx(tmp_path, '{ plugins: [ { source: plugA } ] }\n')
    a = c.paths.plugins_dir / 'plugA'
    a.mkdir(parents=True)
    (a / 'plugin.hu').write_text('{ name: plugA  plugins: [ { source: srcplug } ] }\n')
    ok, msg = actions.plugin_remove(c, 'srcplug')
    assert not ok and 'declared by the plugin plugA' in msg
    assert 'srcplug' in (a / 'plugin.hu').read_text()          # its manifest untouched


@pytest.mark.parametrize('key', ['dirs.app', 'scope', 'machine', 'disabled-drivers', 'driver-preference'])
def test_layout_settings_drop_the_glue_locations_cache(tmp_path, key):
    c = _ctx(tmp_path)
    c.paths.glue_locations_file.parent.mkdir(parents=True, exist_ok=True)
    c.paths.glue_locations_file.write_text('stale\n')
    actions._invalidate_for(c, key)
    assert not c.paths.glue_locations_file.exists()


def test_a_theme_key_your_top_config_sets_is_edited_there(tmp_path, monkeypatch):
    c = _ctx(tmp_path, '{ theme: { colors: { accent: "#ff0000" } } }\n')
    monkeypatch.setattr(actions, 'edit_target', lambda ctx, create=False: ('/prim/p.hu', 'prim'))
    assert actions.theme_target(c, 'colors.accent') == (str(c.paths.user_config_file), 'top config')
    assert actions.theme_target(c, 'colors.title') == ('/prim/p.hu', 'prim')


def test_dotfiles_units_reuse_the_pipeline_resolution():
    unit = types.SimpleNamespace(driver='dotfiles', comp='x-dotfiles')
    routes = types.SimpleNamespace(resolve_resilient=lambda *a, **k: pytest.fail('re-resolved'))
    cfg = object()
    c = types.SimpleNamespace(routes=routes, config=cfg, runner=None, paths=None,
                              pipeline_units=(id(routes), id(cfg), {'dotfiles\\x-dotfiles': unit}))
    _drv, units = actions.dotfiles_units(c)
    assert units == [unit]


def test_the_uninstall_queue_has_a_cli(tmp_path, capsys):
    # G4: `configsys uninstall list|add|rm|clear` (TUI `x`'s queue; clear_uninstall's caller)
    from configsys import app
    base = ['--home', str(tmp_path), '--os', 'pop_os!:24.04']
    assert app.main(base + ['uninstall', 'add', 'btop']) == 0
    assert app.main(base + ['uninstall', 'list']) == 0
    assert '- btop' in capsys.readouterr().out
    assert app.main(base + ['uninstall', 'clear']) == 0
    assert app.main(base + ['uninstall', 'list']) == 0
    assert 'nothing staged' in capsys.readouterr().out
    assert app.main(base + ['uninstall', 'add', 'nosuchtool']) == 1
