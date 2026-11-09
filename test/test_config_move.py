'''Per-setting NATURE routing + the local<->primary MOVE for machine settings. A 'uniform' setting
(driver-preference, dirs.app...) defaults into the primary plugin (portable); a 'machine' setting
(scope, dirs.system...) defaults to this box's top config. `m` / `config move` carries a setting's
value the other way and clears the source. File-based (like save_theme_to_primary), so it works
without the plugin being a loaded Config layer.'''

import types

from configsys import actions, layers, plugins
from configsys.config import Config


def _ctx_with_primary(tmp_path, user_body='{ plugins: [ { source: myprim  primary: true } ] }\n'):
    pdir = tmp_path / 'plugins'
    (pdir / 'myprim').mkdir(parents=True)
    (pdir / 'myprim' / 'plugin.hu').write_text(
        f'{{\n  name: myprim\n  requires-abi: {plugins.ABI_VERSION}\n  data: [ data.hu ]\n}}\n',
        encoding='utf-8')
    prim_data = pdir / 'myprim' / 'data.hu'
    prim_data.write_text('{ }\n', encoding='utf-8')
    repo = tmp_path / 'config.hu'
    repo.write_text('{ scope: user }\n', encoding='utf-8')
    user = tmp_path / 'user.hu'
    user.write_text(user_body, encoding='utf-8')

    def load():
        return Config([layers.Layer(str(repo), 'repo', layers.materialize_string(repo.read_text())),
                       layers.Layer(str(user), 'user', layers.materialize_string(user.read_text()))])

    ctx = types.SimpleNamespace(config=load(),
                                paths=types.SimpleNamespace(user_config_file=str(user),
                                                            plugins_dir=pdir, env={}))
    ctx.invalidate = lambda: setattr(ctx, 'config', load())
    return ctx, user, prim_data


def test_nature_routes_default_edit(tmp_path):
    ctx, user, prim = _ctx_with_primary(tmp_path)
    # uniform -> primary plugin
    _ok, label = actions.set_config_setting(ctx, 'driver-preference', ['native', 'source'])
    assert label == 'myprim'
    assert plugins.read_list_section(str(prim), 'driver-preference') == ['native', 'source']
    assert plugins.read_list_section(str(user), 'driver-preference') == []
    # machine -> this box's top config, even though a primary exists
    _ok, label = actions.set_config_setting(ctx, 'scope', ['system'])
    assert label == 'top config'
    assert plugins.read_scalar_section(str(user), 'scope') == 'system'
    assert plugins.read_scalar_section(str(prim), 'scope') is None


def test_config_settings_surfaces_nature_and_home(tmp_path):
    ctx, _user, _prim = _ctx_with_primary(tmp_path)
    actions.set_config_setting(ctx, 'driver-preference', ['native'])   # -> primary (uniform)
    s = actions.config_settings(ctx)
    assert s['driver-preference']['nature'] == 'uniform'
    assert s['driver-preference']['home'] == 'primary'
    assert s['driver-preference']['home_label'] == 'myprim'
    assert s['driver-preference']['target'] == 'myprim'
    assert s['scope']['nature'] == 'machine'
    assert s['scope']['home'] is None                     # unset -> built-in default
    assert s['scope']['target'] == 'top config'           # a fresh machine edit lands local


def test_move_local_to_primary_and_back(tmp_path):
    ctx, user, prim = _ctx_with_primary(tmp_path)
    actions.set_config_setting(ctx, 'scope', ['system'])              # machine -> local
    assert actions.config_settings(ctx)['scope']['home'] == 'local'

    ok, msg = actions.move_config_setting(ctx, 'scope')              # local -> primary
    assert ok and 'myprim' in msg
    assert plugins.read_scalar_section(str(prim), 'scope') == 'system'
    assert plugins.read_scalar_section(str(user), 'scope') is None    # source cleared
    assert actions.config_settings(ctx)['scope']['home'] == 'primary'

    ok, _msg = actions.move_config_setting(ctx, 'scope')            # primary -> local
    assert ok
    assert plugins.read_scalar_section(str(user), 'scope') == 'system'
    assert plugins.read_scalar_section(str(prim), 'scope') is None


def test_splash_setting_roundtrip_and_disable(tmp_path):
    ctx, user, prim = _ctx_with_primary(tmp_path)
    assert ctx.config.splash() is None                          # unset -> built-in default

    # uniform nature -> a default edit lands in the primary plugin
    _ok, label = actions.set_config_setting(ctx, 'splash', ['aquarium'])
    assert label == 'myprim'
    assert plugins.read_scalar_section(str(prim), 'splash') == 'aquarium'
    s = actions.config_settings(ctx)
    assert s['splash']['nature'] == 'uniform' and s['splash']['home'] == 'primary'

    # a local disable is what the accessor reads (the user layer IS loaded)
    actions.set_config_setting(ctx, 'splash', ['off'], target=str(user))
    assert ctx.config.splash() == 'off'
    actions.set_config_setting(ctx, 'splash', [], target=str(user))   # clear local
    assert plugins.read_scalar_section(str(user), 'splash') is None


def test_move_carries_dir_value(tmp_path):
    ctx, user, prim = _ctx_with_primary(tmp_path)
    actions.set_config_setting(ctx, 'dirs.system', ['/srv/apps'])    # machine dir -> local
    ok, _msg = actions.move_config_setting(ctx, 'dirs.system')       # -> primary
    assert ok
    assert plugins.read_dirs(str(prim)).get('system') == '/srv/apps'
    assert 'system' not in plugins.read_dirs(str(user))


def test_move_guards(tmp_path):
    ctx, _user, _prim = _ctx_with_primary(tmp_path)
    ok, msg = actions.move_config_setting(ctx, 'scope')             # nothing set yet
    assert not ok and 'default' in msg

    # no primary blessed: local setting has nowhere to move
    ctx2, _u, _p = _ctx_with_primary(tmp_path / 'np', user_body='{ }\n')
    actions.set_config_setting(ctx2, 'driver-preference', ['native'])
    ok, msg = actions.move_config_setting(ctx2, 'driver-preference')
    assert not ok and 'primary' in msg


def test_config_settings_resolves_the_primary_once(tmp_path, monkeypatch):
    # review-2026-11-2 actions-26: plugins.declared + layer_files ran twice per setting (45 each)
    ctx, user, prim = _ctx_with_primary(tmp_path)
    actions.set_config_setting(ctx, 'driver-preference', ['native'])          # -> primary
    actions.set_config_setting(ctx, 'scope', ['system'])                      # -> top config
    actions.set_config_setting(ctx, 'locations', ['btop=/opt/btop'])          # a map, local
    actions.set_config_setting(ctx, 'dirs.app', ['~/apps'])                   # a dir, primary
    # the per-setting answer each row used to compute on its own — what the one pass must equal
    expect = {k: (actions._setting_home(ctx, k), actions._setting_target(ctx, k)[1])
              for k in actions.CONFIG_SETTINGS}
    calls = {'declared': 0, 'layer_files': 0, 'parse': 0}
    for name in ('declared', 'layer_files'):
        real = getattr(plugins, name)
        monkeypatch.setattr(plugins, name, lambda *a, _r=real, _n=name, **k: (
            calls.__setitem__(_n, calls[_n] + 1), _r(*a, **k))[1])
    real_mat = layers.materialize_string
    monkeypatch.setattr(layers, 'materialize_string', lambda *a, **k: (
        calls.__setitem__('parse', calls['parse'] + 1), real_mat(*a, **k))[1])
    s = actions.config_settings(ctx)
    assert calls['declared'] == 1 and calls['layer_files'] == 1
    assert calls['parse'] <= 2                                 # the top config + the primary, once each
    got = {k: ((v['home'], v['home_label']), v['target']) for k, v in s.items()}
    assert got == expect
    assert s['locations']['home'] == 'local' and s['dirs.app']['home'] == 'primary'


# -- review-2026-11-2 config-layers-17: a top-config-only setting never "lives" in the primary --------

def test_a_top_config_only_setting_in_the_primary_reads_ignored(tmp_path):
    ctx, user, prim = _ctx_with_primary(tmp_path)
    prim.write_text('{ primary-verify: signed }\n', encoding='utf-8')
    repo = tmp_path / 'config.hu'
    ctx.config = Config([layers.Layer(str(repo), 'repo', layers.materialize_string(repo.read_text())),
                         layers.Layer(str(prim), 'primary', layers.materialize_string(prim.read_text())),
                         layers.Layer(str(user), 'user', layers.materialize_string(user.read_text()))])
    assert ctx.config.machine_setting_source('primary-verify') is None
    info = actions.config_settings(ctx)['primary-verify']
    assert info['value'] == 'off' and info['source'] is None and info['home'] is None
    assert info['target'] == 'top config' and 'ignored in myprim' in info['note']
    assert 'note' not in actions.config_settings(ctx)['scope']
    # set in the top config: it lives there, and the primary's copy is still named as ignored
    actions.set_config_setting(ctx, 'primary-verify', ['signed'])
    info = actions.config_settings(ctx)['primary-verify']
    assert info['home'] == 'local' and info['value'] == 'signed' and 'note' in info
