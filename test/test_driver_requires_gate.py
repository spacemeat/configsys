'''Driver gates: a driver is valid only where its own `requires:` can be met (the DERIVED gate,
resolve.gated_context), plus the explicit `drivers: { X: { when: … } }` gate for facts that aren't
requirements (brew: glibc only; aur: Arch only).

Before the derived gate, a method whose driver's prerequisite had no route here (snap without snapd,
an AppImage on musl or on the libfuse2-less image OSes) was still listed as "alternative here — pin
to use", and an only-method component was an unmet-requirement error row. Now the method simply isn't
a candidate: the component reads "no binding here" (OS availability) with the reason attached, `where`
says why, and a provider-pin that makes the requirement satisfiable (`pins: { glibc: gcompat }`)
opens the driver. Validity only — where a driver IS valid, nothing shifts.'''

import pytest

from configsys.app import Context, build_parser, where_report
from configsys.resolve import (DEFAULT_DRIVER_PREFERENCE, ResolveError, candidate_bindings,
                               gated_context)
from configsys.routes import Resolver

ROUTES = 'routes.hu'

# -- the mechanism, on miniature routes -------------------------------------------------------------

OS = '''os: {
    linux:  { provides: python3 }
    glibcy: { using: linux  native: apt  provides: glibc }
    musly:  { using: linux  native: apk }
    zippy:  { using: linux  native: zip }
}'''
DRIVERS = '''drivers: {
    snap:     { requires: snapd }
    appImage: { requires: [ fuse, glibc ] }
    brew:     { requires: homebrew  when: "glibcy" }
    zip:      { requires: zipd }
}'''
COMPS = '''
    snapd:    { install: [ { via: native  when: "glibcy" } ] }
    fuse:     { install: [ { via: native } ] }
    shim:     { provides: glibc  standing: never-auto  install: [ { via: native  when: "musly" } ] }
    homebrew: { install: [ { via: script  install-cmd: x  uninstall-cmd: y } ] }
    zipd:     { install: [ { via: snap } ] }
    app:      { install: [ { via: snap }  { via: appImage  url: "https://x/app.AppImage" } ] }
    snaponly: { install: [ { via: snap } ] }
    native1:  { install: [ { via: native } ] }
'''


def _routes(tmp_path):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  ' + DRIVERS + '  components: { ' + COMPS + ' } }')
    return str(p)


def _res(tmp_path, block, **kw):
    return Resolver(_routes(tmp_path), block, None, 'x86_64', **kw)


def test_unmet_driver_requires_gate_the_driver(tmp_path):
    r = _res(tmp_path, 'musly')
    ctx = r.context()
    assert {'snap', 'appImage'} <= set(ctx.derived_gates)          # no snapd / no glibc provider
    assert 'nothing provides "snapd"' in ctx.derived_gates['snap']
    assert r.candidates('snaponly') == []
    with pytest.raises(ResolveError) as e:
        r.resolve_names(['snaponly'])
    msg = str(e.value)
    assert msg.startswith('no binding for snaponly in this context')
    assert "snap: the snap driver can't work here" in msg


def test_valid_where_requires_resolve(tmp_path):
    r = _res(tmp_path, 'glibcy')
    assert r.context().derived_gates == {}
    assert {c['via'] for c in r.candidates('app')} == {'snap', 'appImage'}


def test_gate_is_a_fixpoint_over_transitive_requires(tmp_path):
    # zip requires zipd, whose only method is snap; snap requires snapd, absent on zippy -> both gated
    ctx = _res(tmp_path, 'zippy').context()
    assert {'snap', 'zip'} <= set(ctx.derived_gates)
    # and a `via: native` binding that reaches the gated manager is gated with it
    r = _res(tmp_path, 'zippy')
    assert r.candidates('native1') == []


def test_provider_pin_opens_the_driver(tmp_path):
    # the glibc shim is never-auto: without a pin appImage is gated on musl; the pin opens it
    pinned = _res(tmp_path, 'musly', pins={'glibc': 'shim'})
    assert 'appImage' not in pinned.context().derived_gates
    units = pinned.resolve_names(['app'])
    assert 'appImage\\app' in units and 'apk\\shim' in units


def test_soft_pins_never_open_a_gate(tmp_path):
    r = _res(tmp_path, 'musly')
    units, errs = r.resolve_resilient(['app'], soft_pins={'glibc': 'shim'})
    assert 'app' in errs and not units


def test_explicit_gate_keeps_its_own_reason(tmp_path):
    ctx = _res(tmp_path, 'musly').context()
    assert 'brew' in ctx.gated_drivers and 'brew' not in ctx.derived_gates


def test_gated_context_is_cached_and_keyed_by_pins(tmp_path):
    r = _res(tmp_path, 'musly')
    assert r.context() is r.context()
    other = gated_context(r.cascade, r.components, r.drivers, 'musly', None, 'x86_64', (),
                          {'glibc': 'shim'}, r.overrides, r.preference, r.candidate_only)
    assert other is not r.context() and 'appImage' not in other.derived_gates


# -- the shipped routes -----------------------------------------------------------------------------

@pytest.fixture(scope='module')
def real():
    cache = {}

    def get(block, version=None, **kw):
        key = (block, version, tuple(sorted(kw.get('pins', {}).items())))
        if key not in cache:
            cache[key] = Resolver(ROUTES, block, version, 'x86_64', **kw)
        return cache[key]
    return get


def _never(r, via):
    ctx = r.context()
    for comp in r.components.values():
        assert not any(b.via == via for b in candidate_bindings(comp, r.cascade, ctx)), comp.name


@pytest.mark.parametrize('block,version', [('alpine', None), ('void_musl', None), ('chimera', None),
                                           ('fedora_atomic', '41'), ('kde_linux', None)])
def test_real_appimage_gated_without_glibc_or_libfuse2(real, block, version):
    r = real(block, version)
    assert 'appImage' in r.context().derived_gates
    _never(r, 'appImage')


@pytest.mark.parametrize('block,version', [('opensuse_tumbleweed', None), ('void', None),
                                           ('alpine', None), ('fedora_atomic', '41'),
                                           ('kde_linux', None), ('amzn', None)])
def test_real_snap_gated_where_snapd_has_no_method(real, block, version):
    r = real(block, version)
    assert 'snap' in r.context().derived_gates
    _never(r, 'snap')
    with pytest.raises(ResolveError) as e:
        r.resolve_names(['nextcloud'])                  # snap-only
    assert "the snap driver can't work here" in str(e.value)


@pytest.mark.parametrize('block,version', [('ubuntu', '24.04'), ('fedora', '42'), ('arch', None),
                                           ('void', None), ('opensuse_tumbleweed', None)])
def test_real_appimage_valid_on_glibc_desktops(real, block, version):
    r = real(block, version)
    assert 'appImage' not in r.context().gated_drivers
    assert any(c['via'] == 'appImage' for c in r.candidates('olive'))


@pytest.mark.parametrize('block,version', [('ubuntu', '24.04'), ('fedora', '42'), ('arch', None)])
def test_real_snap_valid_where_snapd_installs(real, block, version):
    assert 'snap' not in real(block, version).context().gated_drivers


def test_real_gcompat_pin_opens_appimage_on_alpine(real):
    units = real('alpine', pins={'glibc': 'gcompat'}).resolve_names(['ghostty'])
    assert 'appImage\\ghostty' in units and 'apk\\gcompat' in units


def test_real_where_names_the_derived_gate(tmp_path):
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'alpine', 'inspect']))
    text = '\n'.join(where_report(ctx, 'ghostty'))
    line = next(ln for ln in text.splitlines() if 'via appImage' in ln)
    assert "not a candidate: the appImage driver can't work here" in line
    assert 'pin to use' not in line


# -- aur: ranked right after native; an explicit Arch-only gate -------------------------------------

def test_aur_ranks_right_after_native():
    assert DEFAULT_DRIVER_PREFERENCE[:2] == ['native', 'aur']


def test_real_aur_gate_is_explicit_and_arch_only(real):
    void = real('void')                                 # Void has base-devel, so only `when:` excludes it
    assert 'aur' in void.context().gated_drivers and 'aur' not in void.context().derived_gates
    _never(void, 'aur')
    assert 'aur' not in real('arch').context().gated_drivers


def test_real_aur_beats_flatpak_by_preference_on_arch(real):
    # the aur bindings no longer carry `when: "arch"` — preference, not specificity, picks them
    r = real('arch')
    for name in ('brave', 'chrome'):
        win = [c for c in r.candidates(name) if c['default']]
        assert win and win[0]['via'] == 'aur' and win[0]['when'] is None, name


def test_disabling_a_drivers_prerequisite_reads_unmet_not_dangling():
    # snap on Arch needs snapd, which only installs via aur: disable aur and a snap-only pick is
    # `unmet` (your setting broke it), named as such — not `dangling` (gone from this OS)
    from types import SimpleNamespace
    from configsys.stranded import classify_unroutable
    r = Resolver(ROUTES, 'arch', None, 'x86_64', disabled=['aur'])
    status, detail = classify_unroutable(SimpleNamespace(routes=r), ['nextcloud'])['nextcloud']
    assert status == 'unmet' and 'snap' in detail and 'aur' in detail
    r = Resolver(ROUTES, 'opensuse_tumbleweed', None, 'x86_64')
    assert classify_unroutable(SimpleNamespace(routes=r), ['nextcloud'])['nextcloud'][0] == 'dangling'
