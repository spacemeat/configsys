'''The Homebrew route sweep: the driver-wide VALIDITY gate (`drivers: { brew: { when: … } }`),
brew's place in driver-preference (just ahead of tarball), and the brew bindings it enables.

The gate is validity-only — like a false `when:` / `cpu-names:` the gated driver's bindings are
simply not candidates — and adds NO specificity, so where brew IS valid it competes purely by
preference: an ungated native still beats it, an ungated tarball loses to it.'''

import os

import pytest

from configsys import routecheck, routes
from configsys.app import Context, build_parser, where_report
from configsys.resolve import (DEFAULT_DRIVER_PREFERENCE, _select, candidate_bindings,
                               driver_gate_reason)
from configsys.routes import Resolver

HERE = os.path.dirname(__file__)
ROUTES = os.path.join(HERE, '..', 'routes.hu')

# a miniature OS tree: glibc + musl siblings, a native-less glibc OS, and a brew-native OS
OS = '''os: {
    linux:         { provides: python3 }
    glibc_linux:   { using: linux  provides: glibc }
    debian:        { using: glibc_linux  native: apt }
    atomic:        { using: glibc_linux  native: brew }
    nonative:      { using: glibc_linux  provides: [ curl ] }
    alpine:        { using: linux  native: apk }
    muslbrew:      { using: linux  native: brew }
}'''
DRIVERS = 'drivers: { brew: { requires: homebrew  when: "glibc_linux" }  tarball: { requires: curl } }'
COMPS = '''
    homebrew: { install: [ { via: script  install-cmd: x  uninstall-cmd: y } ] }
    curl:     { install: [ { via: native } ] }
    nat:      { install: [ { via: native }  { via: brew  name: nat } ] }
    tar:      { install: [ { via: tarball  installDir: "$CONFIGSYS_APP_DIR/tar"  url: "https://x/tar.tgz" }
                           { via: brew  name: tar } ] }
    only:     { install: [ { via: brew  name: only } ] }
    natonly:  { install: [ { via: native } ] }
'''


def _write(tmp_path, comps=COMPS, drivers=DRIVERS):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  ' + drivers + '  components: { ' + comps + ' } }')
    return str(p)


def _res(tmp_path, block, **kw):
    return Resolver(_write(tmp_path, **kw), block, None, 'x86_64')


def _vias(r, name):
    return {c['via'] for c in r.candidates(name)}


# -- the gate: validity only ---------------------------------------------------------------

def test_gate_makes_brew_invalid_on_musl_and_valid_on_glibc(tmp_path):
    assert 'brew' in _vias(_res(tmp_path, 'debian'), 'nat')
    assert 'brew' in _vias(_res(tmp_path, 'nonative'), 'only')
    alp = _res(tmp_path, 'alpine')
    assert _vias(alp, 'nat') == {'native'}              # brew is not a candidate on musl
    assert alp.candidates('only') == []                 # a brew-only component is unroutable there
    _u, errs = alp.resolve_resilient(['only'])
    assert 'only' in errs


def test_gate_covers_a_native_binding_that_reaches_the_gated_manager(tmp_path):
    # `via: native` on an OS whose native manager IS brew: brew's gate applies to it too
    mb = _res(tmp_path, 'muslbrew')
    assert mb.candidates('natonly') == []
    ok = _res(tmp_path, 'atomic')                       # glibc + native brew: valid
    assert _vias(ok, 'natonly') == {'native'}
    units, errs = ok.resolve_resilient(['natonly'])
    assert not errs and 'brew\\natonly' in units


def test_gate_adds_no_specificity(tmp_path):
    r = _res(tmp_path, 'debian')
    comp, ctx = r.components['nat'], r.context()
    win, cands, rule = _select(comp, r.cascade, ctx, {}, None, r.candidate_only)
    # had the gate made brew's `glibc_linux` match-set narrower than native's "always", brew would
    # win by most-specific; instead both are raw "always" and preference decides -> native
    assert win.via == 'native' and rule == 'driver-preference' and len(cands) == 2
    win, _c, rule = _select(r.components['tar'], r.cascade, ctx, {}, None, r.candidate_only)
    assert win.via == 'brew' and rule == 'driver-preference'      # brew ranks ahead of tarball


def test_preference_order_brew_just_before_tarball():
    order = DEFAULT_DRIVER_PREFERENCE
    assert order.index('brew') == order.index('tarball') - 1
    assert order.index('appImage') < order.index('brew')
    assert order[:6] == ['native', 'aur', 'flatpak', 'snap', 'native-pkg-file', 'appImage']


def test_bad_gate_in_repo_is_a_loud_config_error(tmp_path):
    from configsys.errors import ConfigError
    with pytest.raises(ConfigError, match='brew'):
        routes.load(_write(tmp_path, drivers='drivers: { brew: { when: "glibc_linux and (" } }'))


def test_where_reason_text(tmp_path):
    r = _res(tmp_path, 'alpine')
    b = [b for b in r.components['nat'].bindings if b.via == 'brew'][0]
    assert driver_gate_reason(b, r.cascade, r.context()) == \
        "the brew driver isn't valid here (drivers: brew when: glibc_linux)"
    nb = r.components['natonly'].bindings[0]
    assert driver_gate_reason(nb, r.cascade, r.context()) is None         # apk isn't gated
    mb = _res(tmp_path, 'muslbrew')
    assert 'native manager' in driver_gate_reason(mb.components['natonly'].bindings[0],
                                                  mb.cascade, mb.context())


# -- routecheck mirrors the gated candidate set ---------------------------------------------

def test_same_via_overlap_only_where_gated_is_not_ambiguous(tmp_path):
    comps = COMPS + '''
        twobrew: { install: [ { via: brew  when: "alpine or debian"  name: a }
                              { via: brew  when: "alpine or atomic"  name: b } ] }'''
    # overlapping only on alpine, where brew is gated out -> never both candidates -> fine
    cascade, components, _d, _co = routes.load(_write(tmp_path, comps=comps))
    routecheck.check_component('twobrew', components['twobrew'], cascade)
    # ungated, the same pair is a genuine same-via ambiguity
    with pytest.raises(Exception, match='overlap'):
        routes.load(_write(tmp_path, comps=comps, drivers='drivers: { brew: { requires: homebrew } }'))


def test_method_tie_lint_ignores_overlap_inside_a_gated_out_driver(tmp_path):
    comps = '''
        tie: { install: [ { via: cargo  when: "alpine"  name: t }  { via: pipx  when: "alpine"  name: t } ] }'''
    gated = 'drivers: { cargo: { when: "glibc_linux" } }'
    cascade, components, _d, _co = routes.load(_write(tmp_path, comps=comps, drivers=gated))
    assert routecheck._method_tie_warnings('tie', components['tie'], cascade) == []
    cascade, components, _d, _co = routes.load(_write(tmp_path, comps=comps, drivers='drivers: {}'))
    assert routecheck._method_tie_warnings('tie', components['tie'], cascade)   # ungated: a tie


def test_gate_naming_an_unknown_os_warns(tmp_path):
    cascade, components, drivers, co = routes.load(
        _write(tmp_path, drivers='drivers: { brew: { when: "glibcc_linux" } }'))
    issues = routecheck.validate(components, cascade, drivers, candidate_only=co)
    assert any(i.kind == 'unknown-os' and 'brew' in i.message for i in issues)


# -- the real routes.hu ------------------------------------------------------------------------

@pytest.fixture(scope='module')
def real():
    cache = {}

    def get(block, version=None):
        if (block, version) not in cache:
            cache[(block, version)] = Resolver(ROUTES, block, version, 'x86_64')
        return cache[(block, version)]
    return get


@pytest.mark.parametrize('block', ['alpine', 'void_musl', 'chimera'])
def test_real_brew_invalid_on_musl(real, block):
    r = real(block)
    ctx = r.context()
    assert 'brew' in ctx.gated_drivers
    for comp in r.components.values():
        assert not any(b.via == 'brew' for b in candidate_bindings(comp, r.cascade, ctx))


@pytest.mark.parametrize('block,version', [('ubuntu', '24.04'), ('fedora', '42'), ('arch', None),
                                           ('kde_linux', None), ('fedora_atomic', '41')])
def test_real_brew_valid_on_glibc(real, block, version):
    r = real(block, version)
    assert 'brew' not in r.context().gated_drivers
    assert 'brew' in _vias(r, 'wrk')


def test_real_native_still_beats_brew(real):
    r = real('ubuntu', '24.04')
    for name in ('tmux', 'htop', 'jq', 'ripgrep', 'fzf'):
        win = [c for c in r.candidates(name) if c['default']]
        assert win and win[0]['via'] == 'native', name


def test_real_homebrew_pulled_when_brew_chosen_off_atomic(real):
    units, errs = real('ubuntu', '24.04').resolve_resilient(['wrk'])
    assert not errs
    assert {'brew\\wrk', 'script\\homebrew', 'apt\\curl', 'apt\\git'} <= set(units)


def test_real_no_homebrew_cycle_on_kde_linux(real):
    # native-less kde_linux: homebrew's curl/git come from the environment, never from brew
    units, errs = real('kde_linux').resolve_resilient(['wrk', 'homebrew', 'curl', 'git'])
    assert 'wrk' not in errs and 'homebrew' not in errs
    assert 'brew\\wrk' in units and 'script\\homebrew' in units
    assert 'brew\\curl' not in units and 'brew\\git' not in units


def test_real_detected_install_keeps_its_method(real):
    # adopt-installed: a component installed via tarball / pipx keeps that method (soft pin)
    r = real('ubuntu', '24.04')
    units, errs = r.resolve_resilient(['lazygit', 'aider'])
    assert not errs and 'brew\\lazygit' in units and 'brew\\aider' in units      # the new default
    units, errs = r.resolve_resilient(['lazygit', 'aider'],
                                      soft_pins={'lazygit': 'tarball', 'aider': 'pipx'})
    assert not errs and 'tarball\\lazygit' in units and 'pipx\\aider' in units
    assert 'brew\\lazygit' not in units and not r.dropped_soft_pins


def test_where_explains_the_gate(tmp_path):
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'alpine', 'inspect']))
    text = '\n'.join(where_report(ctx, 'wrk'))
    assert "(not a candidate: the brew driver isn't valid here (drivers: brew when: glibc_linux)" in text
