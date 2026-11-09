'''review-2026-11-2 D6 — one selection policy: Resolver.select / resolve_at carry the machine's whole
policy (pins, component-names, preference, never-auto, disabled), and resolves outside the load
pipeline leave the Resolver's recorded state alone.'''

from configsys import reportgen, stranded
from configsys.resolve import ResolveError
from configsys.routes import Resolver, Selection, SelectionPolicy

OS = ('os: { linux: { provides: [ python3 ] }  glibc_linux: { using: linux  provides: glibc }  '
      'debian: { using: glibc_linux  native: apt }  fedora: { using: glibc_linux  native: dnf } }')


def _res(tmp_path, comps, *, extra='', pins=None, disabled=None, block='debian', version='12'):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  ' + extra + '  components: { ' + comps + ' } }')
    return Resolver(str(p), block, version, 'x86_64', pins=pins, disabled=disabled)


TOOL = ('tool: { install: [ { via: native } { via: flatpak  hub: flathub  app: org.x.Tool } ] }'
        '  flatpak: { install: [ { via: native } ] }')


def test_policy_is_the_whole_set(tmp_path):
    r = _res(tmp_path, TOOL, pins={'tool': 'flatpak'}, disabled={'snap'})
    p = r.policy
    assert isinstance(p, SelectionPolicy)
    assert p.pins == {'tool': 'flatpak'} and p.disabled == frozenset({'snap'})


def test_select_honors_pins_and_unpinned_asks_the_auto_default(tmp_path):
    r = _res(tmp_path, TOOL, pins={'tool': 'flatpak'})
    sel = r.select('tool')
    assert isinstance(sel, Selection) and sel.binding.via == 'flatpak'
    assert r.select('tool', pins=r.unpinned('tool')).binding.via == 'native'
    assert {b.via for b in sel.candidates} >= {'flatpak'}
    try:
        r.select('nope')
        raise AssertionError('unknown component must raise')
    except ResolveError:
        pass


def test_resolve_at_carries_disabled_drivers_to_another_os(tmp_path):
    # the request coverage matrix (reportgen.coverage) used to resolve each platform WITHOUT the
    # machine's disabled drivers / preference / never-auto set
    r = _res(tmp_path, TOOL, disabled={'apt', 'dnf'})
    units = r.resolve_at(['tool'], 'fedora', '43')
    assert not any(k.startswith('dnf\\tool') for k in units)


def test_coverage_uses_resolve_at(tmp_path, monkeypatch):
    r = _res(tmp_path, TOOL)
    seen = []
    monkeypatch.setattr(r, 'resolve_at', lambda names, block, version=None: seen.append(block) or {})

    class Ctx:
        routes = r
    reportgen.coverage(Ctx(), 'tool')
    assert seen and len(seen) == len(reportgen._PLATFORMS)


def test_resolve_with_roots_leaves_recorded_state_alone(tmp_path):
    r = _res(tmp_path, TOOL)
    r.dropped_soft_pins = {'sentinel': 'kept'}
    out = {}
    r.resolve_with_roots(['tool'], soft_pins={'tool': 'snap'}, out=out)
    assert r.dropped_soft_pins == {'sentinel': 'kept'}
    assert 'tool' in out['dropped_soft_pins']


def test_routes_without_disabled_does_not_mutate_the_resolver(tmp_path):
    r = _res(tmp_path, TOOL, disabled={'apt'})
    before = r.disabled
    assert stranded._routes_without_disabled(r, 'tool') is True
    assert r.disabled is before
