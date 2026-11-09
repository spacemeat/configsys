'''Theme WRITER (plugins nested `theme:` emitter) + the theme action layer (set value, save/load a
theme PLUGIN) behind `configsys theme`. F3 slice 3; the theme model is already config-driven
(resolve_theme), so this is just surgical editing + a plugin snapshot.'''

import types

import pytest

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
    assert sorted(p.name for p in (pdir / 'mytheme').iterdir()) == ['plugin.hu', 'theme.hu']   # no dotfiles/


def test_save_theme_plugin_refuses_a_path_name(tmp_path):
    # review-2026-11-2 actions-23: `theme save ../../x` wrote outside the plugins dir
    ctx, _user, pdir = _ctx(tmp_path)
    before = sorted(str(p) for p in tmp_path.rglob('*'))
    for bad in ('../../escaped', '..', '.hidden', 'a/b', ''):
        with pytest.raises(ValueError):
            actions.save_theme_plugin(ctx, bad)
    assert sorted(str(p) for p in tmp_path.rglob('*')) == before


def test_theme_save_cli_refuses_a_path_name(tmp_path, capsys):
    from configsys.app import main
    assert main(['--home', str(tmp_path), '--os', 'pop', '-q', 'theme', 'save', '../../x']) == 1
    assert 'not a usable theme pack name' in capsys.readouterr().err
    assert not (tmp_path / 'x').exists() and not (tmp_path / '.config' / 'x').exists()


def test_save_theme_plugin_refuses_unsafe_names_the_primary_and_non_theme_plugins(tmp_path):
    # tui-screens-17: the export name is one safe dir segment, and even `force` never rewrites the
    # primary's (or another real plugin's) manifest as a theme-only one
    import pytest
    ctx, _user, pdir = _ctx(tmp_path, '{ plugins: [ { source: "github:nobody/prim"  primary: true } ]  '
                                      'theme: { colors: { accent: "#abcabc" } } }\n')
    before = sorted(p.name for p in tmp_path.iterdir())
    for bad in ('../x', 'a/b', '.hidden', '..', ''):
        with pytest.raises(ValueError):
            actions.save_theme_plugin(ctx, bad, force=True)
    assert sorted(p.name for p in tmp_path.iterdir()) == before and not list(pdir.iterdir())
    for name, manifest in (('prim', '{ name: prim  data: [ prim.hu ] }\n'),
                           ('codey', '{ name: codey  code: drivers.py }\n'),
                           ('datay', '{ name: datay  data: [ theme.hu  comps.hu ] }\n')):
        (pdir / name).mkdir()
        (pdir / name / 'plugin.hu').write_text(manifest, encoding='utf-8')
        with pytest.raises(ValueError):
            actions.save_theme_plugin(ctx, name, force=True)
        assert (pdir / name / 'plugin.hu').read_text(encoding='utf-8') == manifest   # untouched
        assert not (pdir / name / 'theme.hu').exists()
    _p, existed = actions.save_theme_plugin(ctx, 'pack')               # an ordinary pack still works
    _p, _e = actions.save_theme_plugin(ctx, 'pack', force=True)        # …and re-exports over itself
    assert not existed and (pdir / 'pack' / 'theme.hu').exists()


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
