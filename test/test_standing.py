'''The unified `standing:` field (Phase 3) — one knob subsuming the old prefer / candidate-only /
opt-in trio. `never-auto` = valid + listed but never the auto-default (binding/driver) or never
auto-pulled (component-provider); an int = a preference rank (higher wins).'''

import pytest

from configsys.routes import Resolver
from configsys.resolve import ResolveError

OS = 'os: { linux: {}  debian: { using: linux  native: apt } }'


def _resolve(tmp_path, comps, names, drivers='', pins=None):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  drivers: { ' + drivers + ' }  components: { ' + comps + ' } }')
    return set(Resolver(str(p), 'debian', '12', pins=pins).resolve_names(names))


def test_binding_never_auto_is_not_the_default(tmp_path):
    # two methods; flatpak is standing:never-auto -> native wins the default, flatpak stays pinnable
    comps = 'app: { install: [ { via: native }  { via: flatpak  app: x  standing: never-auto } ] }'
    assert 'apt\\app' in _resolve(tmp_path, comps, ['app'])
    assert 'flatpak\\app' in _resolve(tmp_path, comps, ['app'], pins={'app': 'flatpak'})   # still forceable


def test_binding_int_standing_is_a_preference_rank(tmp_path):
    # native and flatpak are both valid + incomparable; standing:1 on flatpak makes it win
    comps = 'app: { install: [ { via: native }  { via: flatpak  app: x  standing: 1 } ] }'
    assert 'flatpak\\app' in _resolve(tmp_path, comps, ['app'])


def test_component_never_auto_is_opt_in(tmp_path):
    # shim provides cap but is standing:never-auto -> never auto-pulled to satisfy `requires: cap`
    comps = '''
        shim:     { provides: cap  standing: never-auto  install: [ { via: native } ] }
        consumer: { requires: cap                        install: [ { via: native } ] }
    '''
    with pytest.raises(ResolveError):
        _resolve(tmp_path, comps, ['consumer'])                       # nothing auto-provides cap
    # a provider-pin enables it
    assert 'apt\\shim' in _resolve(tmp_path, comps, ['consumer'], pins={'cap': 'shim'})


def test_driver_never_auto(tmp_path):
    # a driver-block standing:never-auto marks EVERY binding of that via as never-default
    comps = 'app: { install: [ { via: native }  { via: flatpak  app: x } ] }'
    got = _resolve(tmp_path, comps, ['app'], drivers='flatpak: { standing: never-auto }')
    assert 'apt\\app' in got and 'flatpak\\app' not in got