'''Install-layout dirs in Config: the `dirs:` section (user/system/app/sdk/src) merged into Config
and resolved by Paths as default < config < env. Full C1 — editable machine settings.'''

import types

from configsys import actions, layers, plugins
from configsys.config import Config
from configsys.paths import Paths


def test_paths_dir_precedence_default_config_env():
    # default
    p = Paths(env={'HOME': '/home/x'})
    assert p.dir_var('CONFIGSYS_SDK_DIR') == 'sdks'
    assert str(p.scope_base('system')) == '/opt'
    assert str(p.scope_base('user')) == '/home/x'          # ~ -> HOME
    # config overrides the default
    p.set_config_dirs({'sdk': 'mysdks', 'system': '/srv/opt', 'ignored': 'x'})
    assert p.dir_var('CONFIGSYS_SDK_DIR') == 'mysdks'
    assert str(p.scope_base('system')) == '/srv/opt'
    # env overrides config
    p2 = Paths(env={'HOME': '/home/x', 'CONFIGSYS_SDK_DIR': 'envsdks',
                    'CONFIGSYS_SYSTEMSCOPE_DIR': '/env/opt'})
    p2.set_config_dirs({'sdk': 'cfgsdks', 'system': '/cfg/opt'})
    assert p2.dir_var('CONFIGSYS_SDK_DIR') == 'envsdks'
    assert str(p2.scope_base('system')) == '/env/opt'


def test_install_dir_substitutes_category_from_config():
    p = Paths(env={'HOME': '/home/x'})
    p.set_config_dirs({'app': 'programs'})
    # a route's `installDir: $CONFIGSYS_APP_DIR/lazygit` under user scope
    assert str(p.install_dir('$CONFIGSYS_APP_DIR/lazygit', 'user')) == '/home/x/programs/lazygit'


def test_config_install_dirs_merge_and_source():
    c = Config([
        layers.Layer('repo.hu', 'repo', layers.materialize_string('{ dirs: { app: apps  sdk: sdks } }')),
        layers.Layer('user.hu', 'user', layers.materialize_string('{ dirs: { sdk: "~/mysdks" } }')),
    ])
    assert c.install_dirs() == {'app': 'apps', 'sdk': '~/mysdks'}   # user sdk wins over repo
    assert c.dir_source('sdk') == 'user.hu'                 # set by one of YOUR layers
    assert c.dir_source('app') is None                      # only the repo baseline -> default


def test_set_config_setting_writes_and_clears_dirs(tmp_path):
    user = tmp_path / 'user.hu'
    user.write_text('{ configs: [ dev ] }\n', encoding='utf-8')

    def load():
        return Config([layers.Layer(str(user), 'user', layers.materialize_string(user.read_text()))])
    ctx = types.SimpleNamespace(config=load(), paths=types.SimpleNamespace(
        user_config_file=str(user), plugins_dir=tmp_path / 'plugins', env={}))
    ctx.invalidate = lambda: setattr(ctx, 'config', load())

    ok, _lbl = actions.set_config_setting(ctx, 'dirs.sdk', ['~/sdks2'])
    assert ok
    assert plugins.read_dirs(str(user)) == {'sdk': '~/sdks2'}
    assert ctx.config.install_dirs()['sdk'] == '~/sdks2'
    assert 'configs: [ dev ]' in user.read_text()            # sibling preserved
    actions.set_config_setting(ctx, 'dirs.sdk', [])          # clear -> drop the key
    assert 'sdk' not in plugins.read_dirs(str(user))


def test_config_settings_surfaces_dirs_with_source(tmp_path):
    user = tmp_path / 'user.hu'
    user.write_text('{ dirs: { sdk: "~/mysdks" } }\n', encoding='utf-8')
    cfg = Config([layers.Layer(str(user), 'user', layers.materialize_string(user.read_text()))])
    ctx = types.SimpleNamespace(config=cfg, paths=types.SimpleNamespace(
        env={'CONFIGSYS_APP_DIR': 'envapps'}))
    s = actions.config_settings(ctx)
    assert s['dirs.sdk']['value'] == '~/mysdks' and s['dirs.sdk']['source'] == 'user.hu'
    assert s['dirs.app']['value'] == 'envapps' and 'env $' in s['dirs.app']['source']   # env wins
    assert s['dirs.src']['value'] == 'src' and s['dirs.src']['source'] is None           # default
