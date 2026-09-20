'''A flat `pins:` value that is BOTH a via/driver name AND a component name (pyenv, flatpak, cargo,
clang, cabal, opam, luarocks, sdkman) must classify as a BINDING-pin, not a provider-pin — the same
way in the resolver, `configsys pin` validation, and routecheck. Regression for the collision where
`pins: {python3.13: pyenv}` broke every component that requires python3.13.'''

from configsys.routes import Resolver
from configsys.resolve import pin_via_names

OS = 'os: { linux: {}  debian: { using: linux  native: apt } }'

# `cargo` is a real driver name AND, here, a component. `mytool` can install natively or via cargo;
# `app` requires `mytool`. Pinning `mytool: cargo` is a BINDING-pin (install mytool with cargo).
COMPS = '''
    cargo:  { install: [ { via: native } ] }
    mytool: { install: [ { via: native } { via: cargo  name: mytool } ] }
    app:    { requires: mytool  install: [ { via: native } ] }
'''


def _resolve(tmp_path, names, pins=None):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  components: { ' + COMPS + ' } }')
    return set(Resolver(str(p), 'debian', '12', pins=pins).resolve_names(names))


def test_pin_value_that_is_a_via_name_is_a_binding_pin_even_when_also_a_component():
    assert 'cargo' in pin_via_names()                    # cargo is a via/driver name...
    # ...and here also a component; a pin naming it is a binding-pin, classified via-name-first.


def test_binding_pin_on_a_via_named_component_does_not_break_a_requirer(tmp_path):
    # resolving `app` pulls in `mytool`; the `mytool: cargo` pin must route mytool via cargo, NOT be
    # misread as "cargo provides mytool" (which threw a bogus provider-pin error before the fix).
    got = _resolve(tmp_path, ['app'], pins={'mytool': 'cargo'})
    assert 'cargo\\mytool' in got                        # honored as a binding-pin
    assert 'apt\\mytool' not in got                      # the pinned method won, not the native one
    assert 'apt\\app' in got                             # the requirer resolved cleanly (no error)


def test_unpinned_requirer_takes_the_default_method(tmp_path):
    got = _resolve(tmp_path, ['app'])
    assert 'apt\\mytool' in got and 'apt\\app' in got    # native default, unchanged
