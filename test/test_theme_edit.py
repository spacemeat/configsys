'''Theme WRITER (plugins nested `theme:` emitter) + the theme action layer (set value, save/load a
theme PLUGIN) behind `configsys theme`. F3 slice 3; the theme model is already config-driven
(resolve_theme), so this is just surgical editing + a plugin snapshot.'''

import types

from configsys import actions, layers, plugins
from configsys.config import Config


def _ctx(tmp_path, user_text='{ }\n'):
    repo = tmp_path / 'config.hu'
    repo.write_text('{ }\n', encoding='utf-8')
    user = tmp_path / 'user.hu'
    user.write_text(user_text, encoding='utf-8')
    pdir = tmp_path / 'plugins'
    pdir.mkdir()

    def load():
        return Config([layers.Layer(str(repo), 'repo', layers.materialize_string(repo.read_text())),
                       layers.Layer(str(user), 'user', layers.materialize_string(user.read_text()))])

    ctx = types.SimpleNamespace()
    ctx.paths = types.SimpleNamespace(user_config_file=str(user), plugins_dir=pdir)
    ctx.config = load()
    ctx.invalidate = lambda: setattr(ctx, 'config', load())
    return ctx, user, pdir


def test_theme_writer_roundtrip_nested_and_bare_bool(tmp_path):
    f = tmp_path / 'u.hu'
    f.write_text('{ configs: [ dev ] }\n', encoding='utf-8')
    theme = {'colors': {'brand': '#c88cf0'},
             'pages': {'components': {'component': {'fg': 'brand', 'bold': True},
                                      'gradient': {'from': '#160a22'}}}}
    plugins.set_theme(str(f), theme)
    got = plugins.read_theme(str(f))
    assert got['colors']['brand'] == '#c88cf0'
    assert got['pages']['components']['component']['fg'] == 'brand'
    assert got['pages']['components']['component']['bold'] in (True, 'true')
    assert 'bold: true' in f.read_text()              # bare humon bool, not quoted
    assert 'configs: [ dev ]' in f.read_text()        # sibling preserved


def test_set_theme_value_and_bool_coercion(tmp_path):
    ctx, user, _ = _ctx(tmp_path)
    actions.set_theme_value(ctx, 'colors.accent', '#123456')
    assert ctx.config.theme()['colors']['accent'] == '#123456'
    actions.set_theme_value(ctx, 'pages.components.profile.bold', 'true')
    assert 'bold: true' in user.read_text()                  # bare humon bool, coerced
    actions.set_theme_value(ctx, 'pages.components.gradient.from', '#0a0b0c')
    assert ctx.config.theme()['pages']['components']['gradient']['from'] == '#0a0b0c'
    actions.set_theme_value(ctx, 'colors.accent', None)      # unset a map color override
    assert 'accent' not in ctx.config.theme()['colors']


def test_save_theme_plugin_and_overwrite_guard(tmp_path):
    ctx, _user, pdir = _ctx(tmp_path, '{ theme: { colors: { accent: "#abcabc" } } }\n')
    path, existed = actions.save_theme_plugin(ctx, 'mytheme')
    assert not existed
    assert (pdir / 'mytheme' / 'theme.hu').exists()
    assert (pdir / 'mytheme' / 'plugin.hu').exists()
    _p, existed2 = actions.save_theme_plugin(ctx, 'mytheme')   # refuses without force
    assert existed2
    _p, _e = actions.save_theme_plugin(ctx, 'mytheme', force=True)   # force overwrites
    saved = plugins.read_theme(str(pdir / 'mytheme' / 'theme.hu'))
    assert saved['colors']['accent'] == '#abcabc'


def test_load_theme_applies_it(tmp_path):
    ctx, user, _pdir = _ctx(tmp_path, '{ theme: { colors: { accent: "#abcabc" } } }\n')
    actions.save_theme_plugin(ctx, 'mytheme')
    user.write_text('{ }\n', encoding='utf-8')                # clear the local theme
    ctx.invalidate()
    assert ctx.config.theme()['colors'] == {}
    changed, label = actions.load_theme(ctx, 'mytheme')
    assert changed
    assert ctx.config.theme()['colors']['accent'] == '#abcabc'


def test_load_missing_theme_is_a_noop(tmp_path):
    ctx, _u, _p = _ctx(tmp_path)
    changed, label = actions.load_theme(ctx, 'nope')
    assert changed is False and label is None


def test_theme_plugins_list(tmp_path):
    ctx, _u, _p = _ctx(tmp_path, '{ theme: { colors: { accent: "#111" } } }\n')
    actions.save_theme_plugin(ctx, 't1')
    assert 't1' in actions.theme_plugins(ctx)


def test_copy_page_theme(tmp_path):
    ctx, _u, _ = _ctx(tmp_path, '{ theme: { pages: { components: { component: { fg: error } } } } }\n')
    ok, _label = actions.copy_page_theme(ctx, 'components', 'profiles')
    assert ok
    assert ctx.config.theme()['pages']['profiles']['component']['fg'] == 'error'   # copied onto profiles
    ok2, msg = actions.copy_page_theme(ctx, 'plugins', 'dotfiles')   # nothing to copy
    assert ok2 is False and 'no overrides' in msg


def test_no_primary_theme_target(tmp_path):
    ctx, _u, _p = _ctx(tmp_path)
    assert actions.primary_theme_target(ctx) is None
    ok, msg = actions.save_theme_to_primary(ctx)
    assert ok is False and 'primary' in msg


def test_promote_full_theme_into_primary_and_move(tmp_path):
    # a synced primary plugin declared in the top config, plus a local theme edit to promote
    pdir = tmp_path / 'plugins'
    (pdir / 'myprim').mkdir(parents=True)
    (pdir / 'myprim' / 'plugin.hu').write_text(
        f'{{\n  name: myprim\n  requires-abi: {plugins.ABI_VERSION}\n  data: [ data.hu ]\n}}\n',
        encoding='utf-8')
    (pdir / 'myprim' / 'data.hu').write_text('{ }\n', encoding='utf-8')
    repo = tmp_path / 'config.hu'
    repo.write_text('{ }\n', encoding='utf-8')
    user = tmp_path / 'user.hu'
    user.write_text('{ plugins: [ { source: myprim  primary: true } ]\n'
                    '  theme: { colors: { accent: "#123456" } } }\n', encoding='utf-8')

    def load():
        return Config([layers.Layer(str(repo), 'repo', layers.materialize_string(repo.read_text())),
                       layers.Layer(str(user), 'user', layers.materialize_string(user.read_text()))])

    ctx = types.SimpleNamespace(config=load(),
                                paths=types.SimpleNamespace(user_config_file=str(user), plugins_dir=pdir))
    ctx.invalidate = lambda: setattr(ctx, 'config', load())

    assert actions.primary_theme_target(ctx) == 'myprim'
    ok, label = actions.save_theme_to_primary(ctx)
    assert ok and label == 'myprim'
    saved = plugins.read_theme(str(pdir / 'myprim' / 'data.hu'))
    assert saved['colors']['accent'] == '#123456'             # the edited color kept
    assert 'title' in saved['colors']                         # FULL map, not just the diff
    assert 'component' in saved['pages']['components']         # roles spelled out (drift-immune)
    assert not plugins.read_theme(str(user)).get('colors')    # MOVED — top-config theme cleared
