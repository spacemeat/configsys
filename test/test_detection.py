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
    return lambda ctx, comp, cx, cache, unless_only=None: mapping.get(comp.name)


PROVIDERS = '''
    prov-default: { provides: cap  install: [ { via: native } ] }
    prov-alt:     { provides: cap  standing: never-auto  install: [ { via: native } ] }
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


def test_an_installed_default_method_is_never_traded_for_an_alternative(tmp_path, monkeypatch):
    # routing-09: both installed -> keep the resolved (default) method; adopting the first-listed
    # alternative would move management off it and the next swap would remove it
    comps = 'multi: { install: [ { via: flatpak  app: org.x }  { via: native } ] }'
    r = _resolver(tmp_path, comps)
    units, _ = r.resolve_resilient(['multi'])
    assert 'apt\\multi' in units                                # native is the default here

    class _Drv:
        def get_version(self, rc):
            return '1.0'
    monkeypatch.setattr(detection, 'get_driver', lambda *a, **k: _Drv())
    monkeypatch.setattr(detection, '_installed_via', _installed({'multi': 'flatpak'}))
    assert detection.detect_pins(_ctx(r), units) == {}


def test_cli_targets_resolve_through_the_detection_tier(tmp_path, monkeypatch):
    # B1: `configsys upgrade multi` acts on the adopted flatpak install, not the default apt unit
    from configsys import actions
    comps = 'multi: { install: [ { via: native }  { via: flatpak  app: org.x } ] }'
    r = _resolver(tmp_path, comps)
    monkeypatch.setattr(detection, 'detect_pins', lambda ctx, units, progress=None: {'multi': 'flatpak'})
    ctx = types.SimpleNamespace(routes=r, runner=types.SimpleNamespace(pretend=False), paths=None,
                                config=types.SimpleNamespace(pins=lambda: {}, auto_tighten=lambda: False,
                                                             adopt_installed=lambda: True))
    units, roots = actions.resolve_targets(ctx, ['multi'])
    assert roots == {'flatpak\\multi'} and 'apt\\multi' not in units
