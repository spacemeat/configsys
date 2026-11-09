'''File inclusions (`include:`) — the unified layer stack. An included file's components +
profiles merge in (definitions-only); the includer overrides its includes; cycles and
missing files error clearly; relative paths resolve against the including file's directory.'''

import os

import pytest

from configsys import layers
from configsys.config import Config
from configsys.errors import ConfigError
from configsys.routes import Resolver

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')


def _w(p, text):
    p.write_text(text)
    return str(p)


def _resolver(user_path):
    return Resolver(ROUTES, 'pop_os!', '22.04', 'x86_64', overrides_path=user_path)


def _config(user_path):
    # config.hu path is intentionally absent -> expand() skips it; only the user chain applies
    return Config(layers.expand([('/no/config.hu', 'repo'), (user_path, 'user')]))


# -- components + profiles from includes ----------------------------------

def test_include_adds_a_component_with_provenance(tmp_path):
    _w(tmp_path / 'proj.hu', '{ components: { proj-tool: { install: [ { via: native } ] } } }')
    up = _w(tmp_path / 'user.hu', '{ include: [ ./proj.hu ] }')
    r = _resolver(up)
    assert 'apt\\proj-tool' in r.resolve_names(['proj-tool'])
    assert r.components['proj-tool'].source.endswith('proj.hu')


def test_include_adds_a_profile(tmp_path):
    _w(tmp_path / 'proj.hu', '{ profiles: { pj: [ btop, ripgrep ] } }')
    up = _w(tmp_path / 'user.hu', '{ include: [ ./proj.hu ] }')
    c = _config(up)
    assert c.profile_components('pj') == ['btop', 'ripgrep']   # the included profile merges in
    assert c.profile_source('pj').endswith('proj.hu')


def test_includer_overrides_its_include(tmp_path):
    _w(tmp_path / 'proj.hu', '{ components: { foo: { install: [ { via: native  name: from-proj } ] } } }')
    up = _w(tmp_path / 'user.hu',
            '{ include: [ ./proj.hu ]  components: { foo: { install: [ { via: native  name: from-user } ] } } }')
    r = _resolver(up)
    assert r.components['foo'].source.endswith('user.hu')
    assert r.components['foo'].shadows                       # it overrode the include's foo
    assert r.resolve_names(['foo'])['apt\\foo'].name == 'from-user'


def test_component_bindings_union_across_layers(tmp_path):
    # additive merge across the layer stack: the include defines foo (native), the includer ADDS
    # a flatpak binding -> both survive (union), and each binding keeps its own defining layer
    _w(tmp_path / 'proj.hu', '{ components: { foo: { install: [ { via: native } ] } } }')
    up = _w(tmp_path / 'user.hu',
            '{ include: [ ./proj.hu ]  components: { foo: { install: [ { via: flatpak  app: org.x.Foo } ] } } }')
    r = _resolver(up)
    binds = {b.via: b for b in r.components['foo'].bindings}
    assert set(binds) == {'native', 'flatpak'}               # union, not wholesale replace
    assert binds['native'].source.endswith('proj.hu')        # binding provenance follows its layer
    assert binds['flatpak'].source.endswith('user.hu')


def test_tombstone_removes_component_across_layers(tmp_path):
    # a higher layer's `{}` clears an included component entirely (whole-component removal)
    _w(tmp_path / 'proj.hu', '{ components: { foo: { install: [ { via: native } ] } } }')
    up = _w(tmp_path / 'user.hu', '{ include: [ ./proj.hu ]  components: { foo: {} } }')
    assert _resolver(up).resolve_names(['foo']) == {}


def test_nested_relative_include_resolves_from_including_files_dir(tmp_path):
    sub = tmp_path / 'sub'
    sub.mkdir()
    _w(sub / 'inner.hu', '{ components: { inner: { install: [ { via: native } ] } } }')
    _w(sub / 'proj.hu', '{ include: [ ./inner.hu ] }')       # relative to sub/, not the user dir
    up = _w(tmp_path / 'user.hu', '{ include: [ ./sub/proj.hu ] }')
    assert 'apt\\inner' in _resolver(up).resolve_names(['inner'])


# -- graph integrity ------------------------------------------------------

def test_include_cycle_errors(tmp_path):
    _w(tmp_path / 'a.hu', '{ include: [ ./b.hu ] }')
    _w(tmp_path / 'b.hu', '{ include: [ ./c.hu ] }')
    _w(tmp_path / 'c.hu', '{ include: [ ./b.hu ] }')       # (a cycle back to a root is just ignored)
    with pytest.raises(ConfigError, match='cycle'):
        layers.expand([(str(tmp_path / 'a.hu'), 'user')])


def test_include_not_found_errors(tmp_path):
    up = _w(tmp_path / 'user.hu', '{ include: [ ./nope.hu ] }')
    with pytest.raises(ConfigError, match='not found'):
        layers.expand([(up, 'user')])


def test_diamond_include_dedups(tmp_path):
    _w(tmp_path / 'd.hu', '{ components: { d-comp: { install: [ { via: native } ] } } }')
    _w(tmp_path / 'b.hu', '{ include: [ ./d.hu ] }')
    _w(tmp_path / 'c.hu', '{ include: [ ./d.hu ] }')
    up = _w(tmp_path / 'user.hu', '{ include: [ ./b.hu, ./c.hu ] }')
    names = [os.path.basename(L.path) for L in layers.expand([(up, 'user')])]
    assert names.count('d.hu') == 1                          # merged once


# -- definitions-only -----------------------------------------------------

def test_included_settings_are_ignored_with_a_warning(tmp_path):
    _w(tmp_path / 'proj.hu', '{ scope: system  pins: { steam: flatpak }  profiles: { pj: [ btop ] } }')
    up = _w(tmp_path / 'user.hu', '{ include: [ ./proj.hu ]  scope: user }')
    ls = layers.expand([(up, 'user')])
    c = Config(ls)
    assert c.default_scope() == 'user'                       # includer's own scope, not the include's
    assert c.pins() == {}                                    # include's `pins:` ignored
    warns = layers.ignored_section_warnings(ls)
    assert any('scope' in w for w in warns) and any('pins' in w for w in warns)


# -- review-2026-11-2 A5 (2026-09 A5): a plugin can't include a root layer to demote it ----------------

def _stack(tmp_path, plug_text, prim=None):
    state = tmp_path / 'state'
    (state / 'plugins' / 'plug').mkdir(parents=True, exist_ok=True)
    top = _w(state / 'configsys.hu', '{ scope: system  machine: laptop  disabled-drivers: [ snap ]\n'
                                     '  picks: { laptop: [ btop ] } }')
    (state / 'plugins' / 'plug' / 'plugin.hu').write_text('{ name: plug  requires-abi: 1 }')
    plug = _w(state / 'plugins' / 'plug' / 'plug.hu', plug_text)
    roots = [('/no/config.hu', 'repo'), (plug, 'plugin')]
    if prim is not None:
        (state / 'plugins' / 'mine').mkdir()
        (state / 'plugins' / 'mine' / 'plugin.hu').write_text('{ name: mine  requires-abi: 1 }')
        roots.append((_w(state / 'plugins' / 'mine' / 'mine.hu', prim), 'primary'))
    roots.append((top, 'user'))
    return layers.expand_tolerant(roots, tolerant_roles=('plugin', 'primary'))


def test_a_plugin_including_the_top_config_does_not_demote_it(tmp_path):
    order, warnings = _stack(tmp_path, '{ include: [ ../../configsys.hu ] }')
    cfg = Config(order)
    assert cfg.default_scope() == 'system' and cfg.current_machine() == 'laptop'
    assert 'snap' in cfg.disabled_drivers() and list(cfg.requested()) == ['btop']
    assert [lay.role for lay in order if lay.path.endswith('configsys.hu')] == ['user']
    assert any('root config layer' in w for w in warnings)


def test_a_plugin_including_the_primary_does_not_demote_it(tmp_path):
    order, warnings = _stack(tmp_path, '{ include: [ ../mine/mine.hu ] }', prim='{ splash: plain }')
    assert [lay.role for lay in order if lay.path.endswith('mine.hu')] == ['primary']
    assert any('root config layer' in w for w in warnings)


def test_a_plugin_include_must_stay_in_its_own_checkout(tmp_path):
    outside = _w(tmp_path / 'elsewhere.hu', '{ components: { sneaky: { install: [ { via: native } ] } } }')
    order, warnings = _stack(tmp_path, '{ include: [ %s ] }' % outside)
    assert not any(lay.path == os.path.normpath(outside) for lay in order)
    assert any('inside its own checkout' in w for w in warnings)
    (tmp_path / 'again' / 'state' / 'plugins' / 'plug').mkdir(parents=True)
    (tmp_path / 'again' / 'state' / 'plugins' / 'plug' / 'sub.hu').write_text('{ profiles: { extra: [ btop ] } }\n')
    order, warnings = _stack(tmp_path / 'again', '{ include: [ sub.hu ] }')
    assert any(lay.path.endswith('sub.hu') for lay in order) and not warnings
