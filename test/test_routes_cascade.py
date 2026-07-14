import humon as h
import pytest

from configsys.errors import ConfigError
from configsys.routes import RouteResolver
from configsys.troveio import load


def real_routes(paths_repo=None):
    from pathlib import Path
    routes = Path(__file__).resolve().parent.parent / 'routes.hu'
    return load(routes)


def test_cascade_order_pop_os():
    t = real_routes()
    r = RouteResolver(t, 'pop_os!')
    assert r.cascade_names == ['pop_os!', 'ubuntu', 'debian', 'linux']


def test_cascade_stops_at_dangling_using():
    # a block whose !using points nowhere just ends the chain
    t = h.from_string('{ foo: { !using: nowhere } }')
    r = RouteResolver(t, 'foo')
    assert r.cascade_names == ['foo']


def test_unknown_os_block_raises():
    t = real_routes()
    with pytest.raises(ConfigError):
        RouteResolver(t, 'plan9')


def test_wildcard_inherited_from_debian():
    t = real_routes()
    r = RouteResolver(t, 'pop_os!')
    units = r.resolve_names(['btop'])
    assert set(units) == {'apt\\btop'}
    assert units['apt\\btop'].family == 'apt'
    assert units['apt\\btop'].name == 'btop'


def test_flatpak_binding():
    t = real_routes()
    r = RouteResolver(t, 'ubuntu')
    units = r.resolve_names(['firefox'])
    # firefox + its family !depends (apt\flatpak) auto-added
    assert set(units) == {'flatpak\\firefox', 'apt\\flatpak'}
    fx = units['flatpak\\firefox']
    assert fx.fields['name'] == 'org.mozilla.firefox'
    assert fx.fields['hub'] == 'flathub'
    assert fx.deps == {'apt\\flatpak'}
    assert units['apt\\flatpak'].deps == set()  # base tool has no further deps
