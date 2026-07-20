'''opt-in providers — a component that `provides:` a capability but is marked `opt-in: true`
never gets AUTO-pulled to satisfy someone else's `requires:`. It satisfies the capability only
when explicitly wanted (named in the resolve set / a profile) or named by a provider-pin. This
is the "best-effort shim" primitive: gcompat provides `glibc` on Alpine but must never install
itself silently. Contrast with an ordinary provider, which IS auto-pulled (epel-release).'''

import pytest

from configsys.resolve import ResolveError
from configsys.routes import Resolver

OS = 'os: { linux: {}  debian: { using: linux  native: apt } }'

COMPS = '''
    app:      { requires: cap  install: [ { via: native } ] }
    shim:     { provides: cap  opt-in: true  install: [ { via: native } ] }
    ordinary: { provides: cap2  install: [ { via: native } ] }
    app2:     { requires: cap2  install: [ { via: native } ] }
'''


def _resolve(tmp_path, names, pins=None):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  components: { ' + COMPS + ' } }')
    return set(Resolver(str(p), 'debian', '12', pins=pins).resolve_names(names))


def test_optin_provider_not_auto_pulled(tmp_path):
    with pytest.raises(ResolveError) as e:
        _resolve(tmp_path, ['app'])
    assert 'auto-provides' in str(e.value) and 'shim' in str(e.value)   # error hints the fix


def test_optin_provider_used_when_pinned(tmp_path):
    assert _resolve(tmp_path, ['app'], pins={'cap': 'shim'}) == {'apt\\app', 'apt\\shim'}


def test_optin_provider_used_when_explicitly_wanted(tmp_path):
    # naming the shim seeds it in phase 1 -> it's in inventory before app's requirement closes
    assert _resolve(tmp_path, ['shim', 'app']) == {'apt\\app', 'apt\\shim'}


def test_ordinary_provider_is_auto_pulled(tmp_path):
    # the contrast: a normal provider (no opt-in) DOES auto-pull to satisfy a requirement
    assert _resolve(tmp_path, ['app2']) == {'apt\\app2', 'apt\\ordinary'}


def test_bad_pin_to_optin_that_cannot_provide_here(tmp_path):
    # a provider-pin still respects context: pinning to something unroutable here errors clearly
    os2 = 'os: { linux: {}  debian: { using: linux  native: apt }  other: { using: linux  native: apt } }'
    comps = '''
        app:  { requires: cap  install: [ { via: native } ] }
        shim: { provides: cap  opt-in: true  install: [ { via: native  when: "other" } ] }
    '''
    p = tmp_path / 'r.hu'
    p.write_text('{ ' + os2 + '  components: { ' + comps + ' } }')
    with pytest.raises(ResolveError):
        Resolver(str(p), 'debian', '12', pins={'cap': 'shim'}).resolve_names(['app'])
