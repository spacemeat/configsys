'''review-2026-11-2 B15 — the routing correctness batch: disabled-drivers covers the native manager; a
provider-pin on a capability that is also a component; a `{}` name-drop can't satisfy a hard require;
an unroutable bundle part is skipped with a notice; a soft pin whose method's requires fail is dropped;
an ambiguity never closes a derived driver gate; version-floors act at both levels; Void musl on ARM.'''

from configsys.routes import Resolver

OS = ('os: { linux: { provides: [ python3 ] }  glibc_linux: { using: linux  provides: glibc }  '
      'debian: { using: glibc_linux  native: apt }  '
      'alpine: { using: linux  native: apk } }')


def _res(tmp_path, comps, block='debian', version='12', *, extra='', pins=None, disabled=None,
         plugin=None):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  ' + extra + '  components: { ' + comps + ' } }')
    files = []
    if plugin:
        q = tmp_path / 'plug.hu'
        q.write_text(plugin)
        files = [(str(q), 'plugin')]
    return Resolver(str(p), block, version, 'x86_64', pins=pins, disabled=disabled,
                    plugin_files=files)


def test_disabling_the_native_manager_disables_via_native(tmp_path):
    r = _res(tmp_path, 'tool: { install: [ { via: native } { via: flatpak  hub: flathub  app: org.x.Tool } ] }'
                       '  flatpak: { install: [ { via: native } ] }', disabled={'apt'},
             extra='drivers: { flatpak: { requires: flatpak } }')
    units, errors = r.resolve_resilient(['tool'])
    assert not any(k.startswith('apt\\tool') for k in units)
    # with apt off, the flatpak driver's own requirement (flatpak via apt) can't be met either
    assert 'tool' in errors and 'disabled' in errors['tool']


def test_a_provider_pin_on_a_component_capability_keeps_its_own_pick(tmp_path):
    comps = ('jdk: { install: [ { via: native  name: default-jdk } ] }'
             '  jdk-25: { provides: jdk  install: [ { via: native  name: openjdk-25-jdk } ] }'
             '  scala: { requires: jdk  install: [ { via: native } ] }')
    r = _res(tmp_path, comps, pins={'jdk': 'jdk-25'})
    units, errors = r.resolve_resilient(['jdk', 'scala'])
    assert not errors, errors
    assert 'apt\\jdk' in units and 'apt\\jdk-25' in units
    assert 'apt\\jdk-25' in units['apt\\scala'].deps


def test_a_name_drop_does_not_satisfy_a_hard_require(tmp_path):
    comps = ('libx: { install: [ { via: native } ] }  tool: { requires: libx  install: [ { via: native } ] }')
    r = _res(tmp_path, comps, extra='component-names: { apt: { libx: {} } }')
    units, errors = r.resolve_resilient(['tool'])
    assert 'tool' in errors and 'libx' in errors['tool']
    units, errors = r.resolve_resilient(['libx'])           # a direct pick stays a silent no-op
    assert not errors and not units


def test_an_unroutable_bundle_part_is_skipped_with_a_notice(tmp_path):
    comps = ('a: { install: [ { via: native } ] }  b: { install: [ { via: native  when: "alpine" } ] }'
             '  c: { install: [ { via: native } ] }  bundle: { parts: [ a b c ] }'
             '  other: { install: [ { via: native } ] }  nothing: { parts: [ b ] }')
    r = _res(tmp_path, comps)
    for names in (['bundle'], ['bundle', 'other'], ['other', 'bundle']):
        units, errors = r.resolve_resilient(names, record=True)
        assert {'apt\\a', 'apt\\c'} <= set(units) and 'bundle' not in errors, (names, errors)
        assert [p for p, _why in r.skipped_parts['bundle']] == ['b']
    _u, errors = r.resolve_resilient(['nothing'], record=True)
    assert 'nothing' in errors and 'no part of nothing' in errors['nothing']


def test_a_soft_pin_whose_method_requires_fail_is_dropped(tmp_path):
    comps = ('tool: { install: [ { via: native } { via: tarball  url: "https://x/t.tgz"  requires: glibc } ] }'
             '  curl: { install: [ { via: native } ] }')
    r = _res(tmp_path, comps, block='alpine', version='3.20',
             extra='drivers: { tarball: { requires: curl } }')
    units, errors = r.resolve_resilient(['tool'], soft_pins={'tool': 'tarball'}, record=True)
    assert not errors, errors
    assert 'apk\\tool' in units and 'tool' in r.dropped_soft_pins


def test_an_ambiguous_driver_tool_reports_the_ambiguity_not_dangling(tmp_path):
    comps = ('flatpak: { install: [ { via: native } ] }  flatpak-alt: { provides: flatpak  install: [ { via: native } ] }'
             '  app: { install: [ { via: flatpak  hub: flathub  app: org.x.App } ] }')
    r = _res(tmp_path, comps, extra='drivers: { flatpak: { requires: flatpak } }')
    assert 'flatpak' not in (r.context().derived_gates or {})
    _u, errors = r.resolve_resilient(['app'])
    assert 'ambiguous providers' in errors.get('app', ''), errors


def test_a_version_floor_selects_at_binding_level_too(tmp_path):
    comps = ('py311: { provides: { python3: 3.11 }  install: [ { via: native } ] }'
             '  py313: { provides: { python3: 3.13 }  standing: never-auto  install: [ { via: native } ] }'
             '  tool: { install: [ { via: native  requires: python3 } ] }')
    plain = _res(tmp_path, comps)
    floored = _res(tmp_path, comps, plugin='{ version-floors: { tool: { python3: ">=3.13" } } }')
    pu, _e = plain.resolve_resilient(['tool'])
    fu, fe = floored.resolve_resilient(['tool'])
    assert not fe, fe
    assert 'apt\\py313' not in pu and 'apt\\py313' in fu


def test_void_musl_is_detected_on_arm(tmp_path):
    import os
    from configsys import osdetect, routes
    cascade = routes.load(os.path.join(os.path.dirname(__file__), '..', 'routes.hu'))[0]
    for loader in ('/lib/ld-musl-x86_64.so.1', '/lib/ld-musl-aarch64.so.1', '/lib/ld-musl-armhf.so.1'):
        assert osdetect.refine('void', cascade, env={}, exists=lambda p, L=loader: p == L) == 'void_musl'
    assert osdetect.refine('void', cascade, env={}, exists=lambda p: False) == 'void'
