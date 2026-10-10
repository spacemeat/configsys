'''The appImage driver gate
(`drivers: { appImage: { when: "glibc_linux and not (fedora_atomic or kde_linux)" } }`): AppImages are
glibc builds, and the image-based fedora_atomic / kde_linux ship no libfuse2, so no AppImage method is
a candidate on musl (alpine/chimera/void_musl), fedora_atomic or kde_linux. Before the gate they were
listed as "alternative here — pin to use" and failed on an unmet glibc/libfuse2 require. Validity
only: where AppImage IS valid, nothing shifts. The `glibc` require stays so the gcompat gamble remains
an explicit opt-in.'''

import pytest

from configsys.app import Context, build_parser, where_report
from configsys.resolve import candidate_bindings
from configsys.routes import Resolver

ROUTES = 'routes.hu'


@pytest.fixture(scope='module')
def real():
    cache = {}

    def get(block, version=None):
        if (block, version) not in cache:
            cache[(block, version)] = Resolver(ROUTES, block, version, 'x86_64')
        return cache[(block, version)]
    return get


@pytest.mark.parametrize('block,version', [('alpine', None), ('void_musl', None), ('chimera', None),
                                           ('fedora_atomic', '41'), ('kde_linux', None)])
def test_appimage_never_a_candidate_where_gated(real, block, version):
    r = real(block, version)
    ctx = r.context()
    assert 'appImage' in ctx.gated_drivers
    for comp in r.components.values():
        assert not any(b.via == 'appImage' for b in candidate_bindings(comp, r.cascade, ctx)), comp.name


@pytest.mark.parametrize('block,version', [('ubuntu', '24.04'), ('fedora', '42'), ('arch', None),
                                           ('void', None), ('opensuse_tumbleweed', None)])
def test_appimage_still_valid_on_glibc(real, block, version):
    r = real(block, version)
    assert 'appImage' not in r.context().gated_drivers
    assert any(c['via'] == 'appImage' for c in r.candidates('olive'))


def test_appimage_only_component_declines_cleanly_on_musl(real):
    # was: "nothing auto-provides glibc … pins: { glibc: gcompat }" — now simply no method here
    _u, errs = real('alpine').resolve_resilient(['ghostty'])
    assert 'no binding' in errs['ghostty'] and 'glibc' not in errs['ghostty']


def test_signal_flatpak_default_kept_without_binding_gates(real):
    # signal's AppImage lost its `when: "not alpine"` + never-auto; flatpak still wins by preference
    for block, version in (('fedora', '42'), ('opensuse_tumbleweed', None)):
        win = [c for c in real(block, version).candidates('signal') if c['default']]
        assert win and win[0]['via'] == 'flatpak', block


def test_where_names_the_gate(tmp_path):
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'alpine', 'inspect']))
    text = '\n'.join(where_report(ctx, 'ghostty'))
    assert "the appImage driver isn't valid here (drivers: appImage when: glibc_linux and not (fedora_atomic or kde_linux))" in text
    assert 'pin to use' not in text.split('appImage', 1)[1].splitlines()[0]


def _user_ctx(tmp_path, body):
    cfg = tmp_path / '.config' / 'configsys'
    cfg.mkdir(parents=True)
    (cfg / 'configsys.hu').write_text('{ ' + body + ' }')
    return Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'alpine', 'inspect']))


def test_top_config_can_widen_the_gate_and_gcompat_is_still_the_explicit_opt_in(tmp_path):
    widen = 'drivers: { appImage: { when: "glibc_linux or alpine" } }'
    ctx = _user_ctx(tmp_path, widen)
    _u, errs = ctx.routes.resolve_resilient(['ghostty'])
    assert 'gcompat' in errs['ghostty']                 # widened, but glibc still needs the shim
    ctx = _user_ctx(tmp_path / 'b', widen + '  pins: { glibc: gcompat }')
    units, errs = ctx.routes.resolve_resilient(['ghostty'])
    assert not errs
    assert 'appImage\\ghostty' in units and 'apk\\gcompat' in units
