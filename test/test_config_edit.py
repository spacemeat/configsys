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


def test_set_disabled_drivers_opts_out_dotfiles_and_glue(tmp_path):
    # the config option for making dotfiles/glue management optional — a list of vias to turn off.
    ctx, user = _ctx(tmp_path)
    assert ctx.config.disabled_drivers() == []
    actions.set_config_setting(ctx, 'disabled-drivers', ['dotfiles', 'glue'])
    assert set(ctx.config.disabled_drivers()) == {'dotfiles', 'glue'}
    assert 'disabled-drivers' in user.read_text()


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
    assert set(s) == {'scope', 'driver-preference', 'disabled-drivers', 'auto-tighten', 'adopt-installed',
                      'refresh-before-execute', 'install-overlay', 'reboot-advice', 'splash', 'effects',
                      'orphans-ignore', 'machine', 'primary-push', 'primary-verify',
                      'detect-coexisting', 'installer-shell-writes', 'installer-shell-writes-allow',
                      'locations',
                      'dirs.user', 'dirs.system', 'dirs.app', 'dirs.sdk', 'dirs.src'}
    assert s['scope']['value'] == 'user' and s['scope']['desc'] and s['scope']['man']
    assert s['auto-tighten']['kind'] == 'bool'
    assert s['adopt-installed']['kind'] == 'bool' and s['adopt-installed']['value'] is True
    assert s['dirs.sdk']['kind'] == 'dir' and s['dirs.sdk']['value'] == 'sdks'   # built-in default
    assert s['dirs.user']['value'] == '~'


# -- review-2026-11-2 A2: edits never delete a neighbour or leave an unreadable file ------------------

import pytest  # noqa: E402

from configsys.errors import ConfigError  # noqa: E402


def _cfg(tmp_path, text):
    p = tmp_path / 'configsys.hu'
    p.write_text(text)
    return p


def test_replacing_a_quoted_scalar_keeps_the_next_section(tmp_path):
    p = _cfg(tmp_path, '{\n    machine: "laptop"\n    picks: { laptop: [ btop  ripgrep ]  desk: [ zsh ] }\n'
                       '    pins: { btop: native }\n}\n')
    plugins.set_scalar_section(p, 'machine', 'desk')
    assert layers.materialize_string(p.read_text()) == {
        'machine': 'desk', 'picks': {'laptop': ['btop', 'ripgrep'], 'desk': ['zsh']},
        'pins': {'btop': 'native'}}


def test_replacing_a_quoted_scalar_before_a_multiline_block(tmp_path):
    p = _cfg(tmp_path, '{\n    scope: "user"\n    picks: {\n        laptop: [ btop  ripgrep ]\n    }\n}\n')
    plugins.set_scalar_section(p, 'scope', 'system')
    assert layers.materialize_string(p.read_text()) == {'scope': 'system',
                                                        'picks': {'laptop': ['btop', 'ripgrep']}}


def test_a_one_line_config_keeps_its_other_keys_and_brace(tmp_path):
    p = _cfg(tmp_path, '{ scope: user  machine: laptop  picks: { laptop: [ btop ] }  pins: { btop: native } }')
    plugins.set_scalar_section(p, 'scope', 'system')
    assert layers.materialize_string(p.read_text()) == {
        'scope': 'system', 'machine': 'laptop', 'picks': {'laptop': ['btop']}, 'pins': {'btop': 'native'}}


def test_a_value_configsys_had_to_quote_can_be_edited_again(tmp_path):
    p = _cfg(tmp_path, '{\n    scope: user\n}\n')
    plugins.set_scalar_section(p, 'splash', 'my splash')       # quoted, and the last key
    plugins.set_scalar_section(p, 'splash', 'plain')
    assert layers.materialize_string(p.read_text()) == {'scope': 'user', 'splash': 'plain'}


def test_a_trailing_comment_survives_a_scalar_edit(tmp_path):
    p = _cfg(tmp_path, '{\n    scope: user  // keep me\n}\n')
    plugins.set_scalar_section(p, 'scope', 'system')
    assert '// keep me' in p.read_text() and layers.materialize_string(p.read_text()) == {'scope': 'system'}


def test_insert_skips_a_brace_in_a_trailing_comment_and_fills_an_empty_file(tmp_path):
    p = _cfg(tmp_path, '{\n    scope: user\n}\n// trailing } comment\n')
    plugins.set_pins(p, {'a': 'b'})
    assert layers.materialize_string(p.read_text()) == {'scope': 'user', 'pins': {'a': 'b'}}
    for text in ('', '   \n', '// only a comment\n', '/* old: { x: y } */\n'):
        p = _cfg(tmp_path, text)
        plugins.set_scalar_section(p, 'effects', 'reduced')
        assert layers.materialize_string(p.read_text()) == {'effects': 'reduced'}, text


def test_remove_sections_removes_the_key_not_a_copy_in_a_comment(tmp_path):
    p = _cfg(tmp_path, '{\n    // pins: { steam: flatpak }\n    scope: user\n    pins: { steam: flatpak }\n}\n')
    assert plugins.remove_sections(p, ['pins']) == ['pins']
    assert layers.materialize_string(p.read_text()) == {'scope': 'user'}
    p = _cfg(tmp_path, '{\n    note: "pins: { steam: flatpak }"\n    pins: { steam: flatpak }\n}\n')
    plugins.remove_sections(p, ['pins'])
    assert layers.materialize_string(p.read_text()) == {'note': 'pins: { steam: flatpak }'}


def test_list_values_and_map_keys_are_quoted_when_they_must_be(tmp_path):
    p = _cfg(tmp_path, '{\n}\n')
    plugins.set_list_section(p, 'orphans-ignore', ['my app', 'x'])
    assert plugins.read_list_section(p, 'orphans-ignore') == ['my app', 'x']
    plugins.set_picks(p, {'my laptop': ['btop']})
    assert plugins.read_picks(p) == {'my laptop': ['btop']}
    plugins.set_scalar_section(p, 'locations', 'ripgrep=/h/apps//ripgrep')
    assert plugins.read_scalar_section(p, 'locations') == 'ripgrep=/h/apps//ripgrep'


def test_an_unparseable_file_is_refused_not_edited(tmp_path):
    p = _cfg(tmp_path, '{\n    scope: user\n')                  # missing its brace
    with pytest.raises(ConfigError):
        plugins.set_scalar_section(p, 'scope', 'system')
    assert p.read_text() == '{\n    scope: user\n'


def test_a_text_surgery_slip_is_refused_before_writing(tmp_path, monkeypatch):
    p = _cfg(tmp_path, '{\n    scope: user\n    machine: laptop\n}\n')
    text = p.read_text()
    monkeypatch.setattr(plugins, '_locate_section_span',
                        lambda t, s: (t.index('scope'), t.index('}')))   # a span that eats machine:
    with pytest.raises(ConfigError, match='machine'):
        plugins.set_scalar_section(p, 'scope', 'system')
    assert p.read_text() == text
