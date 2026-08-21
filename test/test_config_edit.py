'''Machine-setting WRITERS (plugins scalar/list section writers) + the shared config action layer
(actions.config_settings / set_config_setting) behind `configsys config`. Same F3 pattern as the
profile slice: surgical .hu writers proven with a round-trip + effective-value check.'''

import types

from configsys import actions, layers, plugins
from configsys.config import Config


# -- surgical scalar / list section writers -------------------------------

def test_scalar_section_roundtrip_and_clear(tmp_path):
    f = tmp_path / 'u.hu'
    f.write_text('{ configs: [ dev ] }\n', encoding='utf-8')
    plugins.set_scalar_section(str(f), 'scope', 'system')
    assert plugins.read_scalar_section(str(f), 'scope') == 'system'
    assert 'configs: [ dev ]' in f.read_text()            # sibling untouched
    plugins.set_scalar_section(str(f), 'scope', None)      # clear -> node removed
    assert plugins.read_scalar_section(str(f), 'scope') is None


def test_list_section_roundtrip_and_clear(tmp_path):
    f = tmp_path / 'u.hu'
    f.write_text('{ }\n', encoding='utf-8')
    plugins.set_list_section(str(f), 'driver-preference', ['native', 'flatpak', 'source'])
    assert plugins.read_list_section(str(f), 'driver-preference') == ['native', 'flatpak', 'source']
    plugins.set_list_section(str(f), 'driver-preference', [])
    assert plugins.read_list_section(str(f), 'driver-preference') == []


# -- the action layer (effective values after a write) --------------------

def _ctx(tmp_path):
    '''A minimal fake Context: a real Config over a repo + a writable user file, reloaded on
    invalidate() — enough to exercise actions.set_config_setting end to end.'''
    repo = tmp_path / 'config.hu'
    repo.write_text('{ scope: user }\n', encoding='utf-8')
    user = tmp_path / 'user.hu'
    user.write_text('{ }\n', encoding='utf-8')

    def load():
        return Config([layers.Layer(str(repo), 'repo', layers.materialize_string(repo.read_text())),
                       layers.Layer(str(user), 'user', layers.materialize_string(user.read_text()))])

    ctx = types.SimpleNamespace()
    ctx.paths = types.SimpleNamespace(user_config_file=str(user), plugins_dir=tmp_path / 'plugins')
    ctx._cfg = load()
    ctx.config = ctx._cfg

    def invalidate():
        ctx.config = load()
    ctx.invalidate = invalidate
    # no primary plugin -> edit_target falls back to the top (user) config
    return ctx, user


def test_set_scope_overrides_repo_default(tmp_path):
    ctx, user = _ctx(tmp_path)
    assert ctx.config.default_scope() == 'user'                    # from repo
    changed, label = actions.set_config_setting(ctx, 'scope', ['system'])
    assert changed and label == 'top config'
    assert ctx.config.default_scope() == 'system'                  # user overrides repo
    assert 'scope: system' in user.read_text()


def test_set_driver_preference_list(tmp_path):
    ctx, _user = _ctx(tmp_path)
    actions.set_config_setting(ctx, 'driver-preference', ['native', 'source'])
    assert ctx.config.driver_preference() == ['native', 'source']


def test_set_auto_tighten_bool_is_bare(tmp_path):
    ctx, user = _ctx(tmp_path)
    assert ctx.config.auto_tighten() is False
    actions.set_config_setting(ctx, 'auto-tighten', ['true'])
    assert ctx.config.auto_tighten() is True
    assert 'auto-tighten: true' in user.read_text()                # bare humon bool, not quoted


def test_clear_setting(tmp_path):
    ctx, _user = _ctx(tmp_path)
    actions.set_config_setting(ctx, 'driver-preference', ['cargo', 'native'])
    assert ctx.config.driver_preference() == ['cargo', 'native']
    actions.set_config_setting(ctx, 'driver-preference', [])        # clear
    assert ctx.config.driver_preference() is None


def test_config_settings_view_has_desc_and_man(tmp_path):
    ctx, _user = _ctx(tmp_path)
    s = actions.config_settings(ctx)
    assert set(s) == {'scope', 'driver-preference', 'auto-tighten', 'adopt-installed',
                      'splash', 'effects',
                      'dirs.user', 'dirs.system', 'dirs.app', 'dirs.sdk', 'dirs.src'}
    assert s['scope']['value'] == 'user' and s['scope']['desc'] and s['scope']['man']
    assert s['auto-tighten']['kind'] == 'bool'
    assert s['adopt-installed']['kind'] == 'bool' and s['adopt-installed']['value'] is True
    assert s['dirs.sdk']['kind'] == 'dir' and s['dirs.sdk']['value'] == 'sdks'   # built-in default
    assert s['dirs.user']['value'] == '~'
