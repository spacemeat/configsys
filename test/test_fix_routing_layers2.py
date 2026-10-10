'''Regressions for follow-up decisions (docs-audit batch B): os:/drivers: in the TOP config are
honored machine-locally (#13); the UNIFORM LAYER RULE — every layer may define profiles/os/drivers,
only top config + primary set machine settings (#14); a `via: native` binding closes its resolved
manager's driver requires/standing (#15); Config.keys() rebind-wins (3a); set_dirs indentation (3b).'''

import os

from configsys import layers, routecheck
from configsys.config import Config
from configsys.routes import Resolver, load

HERE = os.path.dirname(__file__)
ROUTES = os.path.join(HERE, '..', 'routes.hu')
OS = 'os: { linux: {}  debian: { using: linux  native: apt } }'


def _w(path, text):
    path.write_text(text)
    return str(path)


# -- #13 os:/drivers: in the top config ---------------------------------------------------------

def test_top_config_drivers_block_applies_on_this_machine(tmp_path):
    routes = _w(tmp_path / 'routes.hu', '{ ' + OS + '  components: { t: { install: [ '
                '{ via: native }  { via: flatpak  app: a.b  when: "debian" } ] } } }')
    user = _w(tmp_path / 'user.hu', '{ drivers: { native-x: { } }  os: { debian: { using: linux  '
              'native: apt  driver-preference: [ flatpak native ] } } }')
    r = Resolver(routes, 'debian', '12', overrides_path=user)
    assert set(r.resolve_names(['t'])) == {'flatpak\\t'}          # the user os-block tweak won
    assert r.cascade.os_sources['debian'] == os.path.normpath(user)  # provenance -> the user file
    assert r.cascade.driver_sources['native-x'] == os.path.normpath(user)


def test_top_config_never_auto_driver(tmp_path):
    routes = _w(tmp_path / 'routes.hu', '{ ' + OS + '  components: { t: { install: [ '
                '{ via: native }  { via: flatpak  app: a.b  when: "debian" } ] } } }')
    user = _w(tmp_path / 'user.hu', '{ drivers: { flatpak: { standing: never-auto } } }')
    casc, _c, _d, co = load(routes, user)
    assert 'flatpak' in co
    # without the user block the more specific flatpak binding wins; with it, native is the default
    assert set(Resolver(routes, 'debian', '12').resolve_names(['t'])) == {'flatpak\\t'}
    assert set(Resolver(routes, 'debian', '12', overrides_path=user).resolve_names(['t'])) == {'apt\\t'}


def test_retired_key_in_a_user_drivers_block_is_attributed_to_the_user_file(tmp_path):
    routes = _w(tmp_path / 'routes.hu', '{ ' + OS + '  components: { } }')
    user = _w(tmp_path / 'user.hu', '{ drivers: { snap: { opt-in: true } } }')
    casc, comps, drivers, _co = load(routes, user)
    iss = [i for i in routecheck.validate(comps, casc, drivers) if i.kind == 'retired-key']
    assert iss and iss[0].source == os.path.normpath(user)


# -- #14 the uniform layer rule ------------------------------------------------------------------

def test_user_profiles_are_no_longer_retired(tmp_path):
    up = _w(tmp_path / 'user.hu', '{ profiles: { mine: [ btop ] } }')
    prim = _w(tmp_path / 'prim.hu', '{ profiles: { theirs: [ fd ] } }')
    ls = layers.expand([(prim, 'primary'), (up, 'user')])
    assert not any('profiles' in w for w in layers.unknown_section_warnings(ls))
    c = Config(ls)
    assert c.profile_components('mine') == ['btop'] and c.profile_components('theirs') == ['fd']
    assert c.profile_source('mine') == os.path.normpath(up)
    assert c.requested() == {}                                   # profiles never install anything


def test_include_may_define_os_drivers_profiles_but_not_settings(tmp_path):
    _w(tmp_path / 'inc.hu', '{ os: { myos: { using: linux  native: apt } }  drivers: { flatpak: '
       '{ standing: never-auto } }  profiles: { incp: [ btop ] }  picks: { this-machine: [ btop ] } }')
    up = _w(tmp_path / 'user.hu', '{ include: [ ./inc.hu ] }')
    ls = layers.expand([(up, 'user')])
    warns = layers.ignored_section_warnings(ls)
    assert not any('`os:`' in w or '`drivers:`' in w or '`profiles:`' in w for w in warns)
    assert any('`picks:`' in w for w in warns)                   # settings still forbidden there
    c = Config(ls)
    assert c.profile_components('incp') == ['btop'] and c.included() == set()
    routes = _w(tmp_path / 'routes.hu', '{ ' + OS + '  components: { } }')
    casc, _c, _d, co = load(routes, up)
    assert 'myos' in casc.blocks and 'flatpak' in co
    assert casc.os_sources['myos'] == os.path.normpath(str(tmp_path / 'inc.hu'))


def test_retired_machines_configs_warnings_stay(tmp_path):
    up = _w(tmp_path / 'user.hu', '{ configs: [ a ]  machines: { m: [ ] }  orphans-adopt-target: x }')
    w = layers.unknown_section_warnings(layers.expand([(up, 'user')]))
    assert sum('retired' in x for x in w) == 3


# -- #15 native-resolved driver requires -------------------------------------------------------

def test_native_component_on_fedora_atomic_pulls_homebrew(tmp_path):
    user = _w(tmp_path / 'user.hu', '{ components: { t-nat: { install: [ { via: native } ] } } }')
    atomic = Resolver(ROUTES, 'fedora_atomic', '41', overrides_path=user).resolve_names(['t-nat'])
    assert any(rc.comp == 'homebrew' for rc in atomic.values())
    assert any('homebrew' in k for k in atomic['brew\\t-nat'].deps)
    ubuntu = Resolver(ROUTES, 'ubuntu', '24.04', overrides_path=user).resolve_names(['t-nat'])
    assert not any(rc.comp == 'homebrew' for rc in ubuntu.values())


def test_never_auto_on_the_native_manager_covers_via_native(tmp_path):
    routes = _w(tmp_path / 'routes.hu', '{ ' + OS + '  drivers: { apt: { standing: never-auto } }  '
                'components: { t: { install: [ { via: native }  { via: tarball  installDir: "x/t" } ] } } }')
    assert set(Resolver(routes, 'debian', '12').resolve_names(['t'])) == {'tarball\\t'}


# -- 3a / 3b ---------------------------------------------------------------------------------

def test_config_keys_rebind_wins_across_layers(tmp_path):
    lo = _w(tmp_path / 'lo.hu', '{ keys: { global: { quit: q  help: "?" } } }')
    hi = _w(tmp_path / 'hi.hu', '{ keys: { global: { help: q } } }')
    k = Config(layers.expand([(lo, 'repo'), (hi, 'user')])).keys()
    assert k['global']['help'] == 'q'
    assert 'q' not in str(k['global'].get('quit', ''))           # the lower action lost the key


def test_set_dirs_inserts_a_correctly_indented_block(tmp_path):
    from configsys import plugins
    f = tmp_path / 'c.hu'
    f.write_text('{\n    scope: user\n}\n')
    plugins.set_dirs(f, {'app': 'apps2'})
    lines = f.read_text().splitlines()
    assert '    dirs: {' in lines and '        app: apps2' in lines and '    }' in lines
    plugins.set_dirs(f, {'app': 'apps3'})                        # in-place replace keeps the indent
    assert '    dirs: {' in f.read_text().splitlines()
    assert layers.read_setting(f, 'dirs') == {'app': 'apps3'}
