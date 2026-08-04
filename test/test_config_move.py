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
