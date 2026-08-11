'''Detection tier (Phase 1): detect_pins biases resolution toward what's installed — an installed
non-default provider/method wins the auto-slot (below explicit pins). The batched probe is stubbed
via _installed_via so the orchestration is what's tested.'''

import types

from configsys import detection
from configsys.routes import Resolver

OS = 'os: { linux: {}  debian: { using: linux  native: apt } }'


def _resolver(tmp_path, comps):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  components: { ' + comps + ' } }')
    return Resolver(str(p), 'debian', '12')


def _ctx(r, pins=None):
    return types.SimpleNamespace(routes=r, runner=None, paths=None,
                                 config=types.SimpleNamespace(pins=lambda: pins or {}))


def _installed(mapping):
    '''A fake _installed_via: comp.name -> via (installed) or absent (not installed).'''
    return lambda ctx, comp, cx, cache: mapping.get(comp.name)


PROVIDERS = '''
    prov-default: { provides: cap  install: [ { via: native } ] }
    prov-alt:     { provides: cap  opt-in: true  install: [ { via: native } ] }
    consumer:     { requires: cap  install: [ { via: native } ] }
'''


def test_provider_detection_adopts_an_installed_alternative(tmp_path, monkeypatch):
    r = _resolver(tmp_path, PROVIDERS)
    units, _ = r.resolve_resilient(['consumer'])                 # cap -> prov-default (alt is opt-in)
    monkeypatch.setattr(detection, '_installed_via', _installed({'prov-alt': 'native'}))
    assert detection.detect_pins(_ctx(r), units) == {'cap': 'prov-alt'}   # adopt the installed one
    # and the pin actually reroutes on re-resolve
    u2, _ = r.resolve_resilient(['consumer'], soft_pins={'cap': 'prov-alt'})
    assert 'apt\\prov-alt' in u2 and 'apt\\prov-default' not in u2


def test_no_adoption_when_resolved_provider_is_installed(tmp_path, monkeypatch):
    r = _resolver(tmp_path, PROVIDERS)
    units, _ = r.resolve_resilient(['consumer'])
    # both installed: the resolved default stays (nothing to adopt)
    monkeypatch.setattr(detection, '_installed_via', _installed({'prov-default': 'native', 'prov-alt': 'native'}))
    assert detection.detect_pins(_ctx(r), units) == {}


def test_user_pin_left_alone(tmp_path, monkeypatch):
    r = _resolver(tmp_path, PROVIDERS)
    units, _ = r.resolve_resilient(['consumer'])
    monkeypatch.setattr(detection, '_installed_via', _installed({'prov-alt': 'native'}))
    assert detection.detect_pins(_ctx(r, pins={'cap': 'prov-default'}), units) == {}  # user pin wins


def test_nothing_installed_is_a_noop(tmp_path, monkeypatch):
    r = _resolver(tmp_path, PROVIDERS)
    units, _ = r.resolve_resilient(['consumer'])
    monkeypatch.setattr(detection, '_installed_via', _installed({}))
    assert detection.detect_pins(_ctx(r), units) == {}          # fresh machine -> byte-identical


def test_method_detection_adopts_installed_via(tmp_path, monkeypatch):
    comps = 'multi: { install: [ { via: native }  { via: flatpak  app: org.x } ] }'
    r = _resolver(tmp_path, comps)
    units, _ = r.resolve_resilient(['multi'])                    # native is the default
    assert 'apt\\multi' in units
    monkeypatch.setattr(detection, '_installed_via', _installed({'multi': 'flatpak'}))
    assert detection.detect_pins(_ctx(r), units) == {'multi': 'flatpak'}   # adopt the installed method
