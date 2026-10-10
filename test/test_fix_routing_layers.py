'''Regressions for the layer-stack fixes (docs-audit batch B): every machine setting is forbidden
(and warned) from include / non-primary plugin layers (#1), the phantom `machine` role and the
reader-less `last-refresh` key are gone and `~` in an include expands against the configsys home (#10),
facets value-vs-spec handling (#2), retired binding keys / never-auto ties in check (#3, #6), and
ships_executable_data counting facet probes + any shipped glue (#9).'''

import os

import pytest

from configsys import config as config_mod
from configsys import layers, routecheck
from configsys.config import Config
from configsys.routes import detect_facets, load

OS = 'os: { linux: {}  debian: { using: linux  native: apt } }'


def _w(path, text):
    path.write_text(text)
    return str(path)


# -- #1 machine settings from include / plugin layers -----------------------------------------

@pytest.mark.parametrize('section,value', [
    ('picks', '{ this-machine: [ btop ] }'), ('machine', 'laptop'),
    ('driver-preference', '[ flatpak native ]'), ('disabled-drivers', '[ snap ]'),
    ('dirs', '{ app: apps2 }'), ('dispositions', '{ btop: seen }'), ('uninstall', '[ btop ]'),
    ('locations', '{ btop: /x }'), ('detect-coexisting', 'false'),
    ('installer-shell-writes', 'allow'), ('installer-shell-writes-allow', '[ btop ]'),
    ('auto-tighten', 'true'), ('scope', 'system'), ('pins', '{ btop: native }'),
])
def test_machine_setting_from_include_and_plugin_is_warned(tmp_path, section, value):
    inc = _w(tmp_path / 'inc.hu', f'{{ {section}: {value} }}')
    plug = _w(tmp_path / 'plug.hu', f'{{ {section}: {value} }}')
    up = _w(tmp_path / 'user.hu', '{ include: [ ./inc.hu ] }')
    ls = layers.expand([(plug, 'plugin'), (up, 'user')])
    warns = layers.ignored_section_warnings(ls)
    assert any(w.startswith(inc) and f'`{section}:`' in w for w in warns)
    assert any(w.startswith(plug) and f'`{section}:`' in w for w in warns)


def test_every_registered_config_setting_is_forbidden_from_a_plugin():
    from configsys.actions import CONFIG_SETTINGS
    forbidden = set(layers._forbidden_by_role()['plugin'])
    assert {k.split('.', 1)[0] for k in CONFIG_SETTINGS} <= forbidden
    # every machine setting is a KNOWN top key (no unknown-key warning on top of the ignored one)
    assert layers.machine_setting_sections() <= (layers._KNOWN_TOP_KEYS
                                                 | layers.machine_setting_sections())


def test_cosmetic_and_retired_keys_are_not_double_warned(tmp_path):
    plug = _w(tmp_path / 'plug.hu', '{ theme: { colors: { a: "#000000" } }  keys: { }  configs: [ x ] }')
    ls = layers.expand([(plug, 'plugin')])
    ign = layers.ignored_section_warnings(ls)
    assert not any('theme' in w or 'keys' in w for w in ign)       # cosmetic: every layer
    assert not any('`configs:`' in w for w in ign)                 # retired has its OWN warning
    assert any('`configs:` retired' in w for w in layers.unknown_section_warnings(ls))


def test_primary_may_set_machine_settings(tmp_path):
    prim = _w(tmp_path / 'prim.hu', '{ picks: { this-machine: [ btop ] }  driver-preference: [ flatpak ] }')
    ls = layers.expand([(prim, 'primary')])
    assert layers.ignored_section_warnings(ls) == []
    c = Config(ls)
    assert c.included() == {'btop'} and c.driver_preference() == ['flatpak']


# -- #10 cleanup -------------------------------------------------------------------------------

def test_machine_roles_has_no_phantom_role():
    assert config_mod._MACHINE_ROLES == ('repo', 'primary', 'user')


def test_last_refresh_is_an_unknown_top_key(tmp_path):
    up = _w(tmp_path / 'user.hu', '{ last-refresh: 123 }')
    warns = layers.unknown_section_warnings(layers.expand([(up, 'user')]))
    assert any('unrecognized top-level key `last-refresh:`' in w for w in warns)


def test_tilde_include_expands_against_the_configsys_home(tmp_path):
    from configsys.paths import Paths
    home = tmp_path / 'sandbox-home'
    home.mkdir()
    _w(home / 'x.hu', '{ components: { from-home: { install: [ { via: native } ] } } }')
    up = _w(tmp_path / 'user.hu', '{ include: [ ~/x.hu ] }')
    try:
        Paths(env={'CONFIGSYS_HOME': str(home), 'HOME': str(tmp_path / 'real-home')})
        ls = layers.expand([(up, 'user')])
        assert any(os.path.realpath(L.path) == os.path.realpath(str(home / 'x.hu')) for L in ls)
    finally:
        layers.set_include_home(None)


# -- #2 facets --------------------------------------------------------------------------------

def _facet_load(tmp_path, user_text, plugin_text=None, include_text=None, trust=None):
    routes = _w(tmp_path / 'routes.hu', '{ ' + OS + '  facets: { gpu: { kind: categorical  '
                'detect: "true"  match: { nvidia: nvidia  amd: amd } } }  components: { } }')
    pf = []
    if plugin_text is not None:
        pf.append((_w(tmp_path / 'plug.hu', plugin_text), 'plugin'))
    if include_text is not None:
        _w(tmp_path / 'inc.hu', include_text)
        user_text = user_text.replace('{', '{ include: [ ./inc.hu ] ', 1)
    user = _w(tmp_path / 'user.hu', user_text)
    warns = []
    casc, _c, _d, _co = load(routes, user, pf, warnings_out=warns, command_trust=trust)
    return casc, warns


def test_user_facet_value_override_is_not_an_untrusted_plugin(tmp_path):
    casc, warns = _facet_load(tmp_path, '{ facets: { gpu: nvidia } }')
    assert not any('facets' in w for w in warns)                  # no false "untrusted plugin"
    assert casc.facet_specs['gpu']['kind'] == 'categorical'       # the repo spec survives


def test_included_facet_spec_follows_its_includers_trust(tmp_path):
    # uniform layer rule (#14): an include may DEFINE a facet; its probe merges when the file is
    # trusted (the user's own include is trusted as the user) and is never mis-worded as "untrusted"
    inc = '{ facets: { x: { kind: version  detect: "echo 1" } } }'
    casc, warns = _facet_load(tmp_path, '{ }', include_text=inc, trust=lambda _p: True)
    assert 'x' in casc.facet_specs and not any('facets' in w for w in warns)
    casc, warns = _facet_load(tmp_path, '{ }', include_text=inc, trust=lambda _p: False)
    assert 'x' not in casc.facet_specs and any('plugin trust' in w for w in warns)


def test_non_dict_facet_spec_is_skipped_with_a_warning(tmp_path):
    casc, warns = _facet_load(tmp_path, '{ machine: m }', plugin_text='{ facets: { cuda: 12 } }',
                              trust=lambda _p: True)
    assert 'cuda' not in casc.facet_specs
    assert any("facet 'cuda' is not a spec map" in w for w in warns)


def test_detect_facets_tolerates_a_non_dict_spec():
    assert detect_facets({'gpu': 'nvidia'}, env={}) == ({}, {})


def test_categorical_facet_value_accepts_a_list():
    spec = {'gpu': {'kind': 'categorical', 'detect': 'true', 'match': {'nvidia': 'x'}}}
    cat, _ver = detect_facets(spec, env={}, run=lambda _c: '', overrides={'gpu': ['nvidia', 'amd']})
    assert cat['gpu'] == frozenset({'nvidia', 'amd'})


# -- #3 / #6 check -----------------------------------------------------------------------------

def test_retired_binding_keys_warn_in_check(tmp_path):
    routes = _w(tmp_path / 'routes.hu', '{ ' + OS + '  components: { t: { install: [ '
                '{ via: native  prefer: 3 }  { via: flatpak  app: a.b  opt-in: true }  '
                '{ via: tarball  installDir: "x/t"  candidate-only: true } ] } } }')
    casc, comps, drivers, _co = load(routes)
    msgs = [i.message for i in routecheck.validate(comps, casc, drivers) if i.kind == 'retired-key']
    assert any('`prefer:`' in m and 'standing: <integer>' in m for m in msgs)
    assert any('`opt-in:`' in m and 'standing: never-auto' in m for m in msgs)
    assert any('`candidate-only:`' in m and 'standing: never-auto' in m for m in msgs)


def test_retired_driver_block_key_warns(tmp_path):
    routes = _w(tmp_path / 'routes.hu', '{ ' + OS + '  drivers: { snap: { candidate-only: true } }  '
                'components: { } }')
    casc, comps, drivers, _co = load(routes)
    assert any(i.kind == 'retired-key' and "driver 'snap'" in i.message
               for i in routecheck.validate(comps, casc, drivers))


def test_retired_component_key_error_has_a_hint(tmp_path):
    from configsys.errors import ConfigError
    routes = _w(tmp_path / 'routes.hu', '{ ' + OS + '  components: { t: { prefer: 2  '
                'install: [ { via: native } ] } } }')
    with pytest.raises(ConfigError, match='standing: <integer>'):
        load(routes)


def test_never_auto_driver_is_not_a_false_method_tie(tmp_path):
    # `zzz-drv` is outside DEFAULT_DRIVER_PREFERENCE, as is `yyy-drv`: both rank last and would tie —
    # but zzz-drv's driver block is never-auto, so resolve._select excludes it; check must too.
    routes = _w(tmp_path / 'routes.hu', '{ ' + OS + '  drivers: { zzz-drv: { standing: never-auto } }  '
                'components: { t: { install: [ { via: yyy-drv }  { via: zzz-drv } ] } } }')
    casc, comps, _d, co = load(routes, validate=False)
    assert co == frozenset({'zzz-drv'})
    assert routecheck._method_tie_warnings('t', comps['t'], casc) == []
    assert routecheck._method_tie_warnings('t', comps['t'], casc, candidate_only=frozenset()) != []


# -- #9 ships_executable_data -----------------------------------------------------------------

def _plugin(tmp_path, data, extra=None):
    from configsys import plugins
    plugins._EXEC_DATA_CACHE.clear()
    pdir = tmp_path / 'plug'
    pdir.mkdir()
    (pdir / 'plugin.hu').write_text('{ name: plug  requires-abi: 1  data: [ routes.hu ] }')
    (pdir / 'routes.hu').write_text(data)
    for rel, text in (extra or {}).items():
        f = pdir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    return pdir


def test_facet_detect_probe_counts_as_executable_data(tmp_path):
    from configsys import plugins
    pdir = _plugin(tmp_path, '{ facets: { gpu: { kind: categorical  detect: "echo nvidia"  '
                   'match: { nvidia: nvidia } } } }')
    assert plugins.ships_executable_data(pdir)


def test_plain_glue_counts_as_executable_data(tmp_path):
    from configsys import plugins
    pdir = _plugin(tmp_path, '{ components: { foo-glue: { install: [ { via: glue  glue: foo } ] } } }',
                   {'glue/bash/foo.sh': 'export FOO=1\n'})
    assert plugins.ships_executable_data(pdir)


def test_glue_snippet_file_alone_counts(tmp_path):
    from configsys import plugins
    pdir = _plugin(tmp_path, '{ components: { } }', {'glue/zsh/foo.zsh': 'alias x=y\n'})
    assert plugins.ships_executable_data(pdir)


def test_pure_data_plugin_is_still_not_trustable(tmp_path):
    from configsys import plugins
    pdir = _plugin(tmp_path, '{ components: { t: { install: [ { via: native } ] } }  '
                   'facets: { cuda: { kind: version } } }')
    assert not plugins.ships_executable_data(pdir)
