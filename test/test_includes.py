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
    up = _w(tmp_path / 'user.hu', '{ include: [ ./proj.hu ]  configs: [ pj ] }')
    c = _config(up)
    assert c.active_profiles == ['pj']
    assert c.profile_components('pj') == ['btop', 'ripgrep']
    assert c.profile_source('pj').endswith('proj.hu')


def test_includer_overrides_its_include(tmp_path):
    _w(tmp_path / 'proj.hu', '{ components: { foo: { install: [ { via: native  name: from-proj } ] } } }')
    up = _w(tmp_path / 'user.hu',
            '{ include: [ ./proj.hu ]  components: { foo: { install: [ { via: native  name: from-user } ] } } }')
    r = _resolver(up)
    assert r.components['foo'].source.endswith('user.hu')
    assert r.components['foo'].shadows                       # it overrode the include's foo
    assert r.resolve_names(['foo'])['apt\\foo'].name == 'from-user'


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
    _w(tmp_path / 'b.hu', '{ include: [ ./a.hu ] }')
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
    _w(tmp_path / 'proj.hu', '{ configs: [ ignored ]  scope: system  profiles: { pj: [ btop ] } }')
    up = _w(tmp_path / 'user.hu', '{ include: [ ./proj.hu ]  configs: [ pj ] }')
    ls = layers.expand([(up, 'user')])
    c = Config(ls)
    assert c.active_profiles == ['pj']                       # include's `configs:` ignored
    assert c.default_scope() is None                         # include's `scope:` ignored
    warns = layers.ignored_section_warnings(ls)
    assert any('configs' in w for w in warns) and any('scope' in w for w in warns)
