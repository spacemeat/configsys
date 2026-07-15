'''Fedora routing against the real routes.hu: native packages, and the per-release
fedora@N toolchain variants (the compat window moves each release).'''

import os

import humon
import pytest

from configsys.errors import ResolveError
from configsys.families import get_family
from configsys.routes import RouteResolver
from configsys.runner import Runner

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')


def _resolver(version):
    return RouteResolver(humon.from_file(ROUTES), 'fedora', version)


def _packages(r, name):
    units, _ = r.resolve_with_roots([name])
    rc = units[[k for k in units if k.endswith(name)][0]]
    return get_family(rc.family, Runner(pretend=True))._packages(rc)


def test_native_packages_route_via_dnf():
    r = _resolver('41')
    units, _ = r.resolve_with_roots(['btop'])
    assert 'dnf\\btop' in units


def test_f41_toolchains():
    r = _resolver('41')
    assert r.cascade_names[0] == 'fedora@41'
    assert _packages(r, 'gcc-13') == ['gcc13', 'gcc13-c++']
    assert _packages(r, 'clang-18') == ['clang18']
    assert _packages(r, 'clang-19') == ['clang']        # system clang -> /usr/bin/clang-19


def test_f42_toolchains():
    r = _resolver('42')
    assert r.cascade_names[0] == 'fedora@42'
    assert _packages(r, 'gcc-14') == ['gcc14', 'gcc14-c++']
    assert _packages(r, 'clang-19') == ['clang19']      # compat on F42, not system
    assert _packages(r, 'clang-20') == ['clang']        # system clang -> /usr/bin/clang-20


def test_gcc13_absent_on_f42():
    # gcc13 compat is gone on F42 (system moved to 15, gcc14 is the compat) -> no route
    with pytest.raises(ResolveError):
        _resolver('42').resolve_with_roots(['gcc-13'])


def test_apod_uses_native_pipx_on_fedora():
    # no pip bootstrap needed: Fedora has an apt... a dnf pipx
    r = _resolver('41')
    units, _ = r.resolve_with_roots(['apod'])
    assert 'dnf\\pipx' in units and 'pip\\pipx' not in units


def test_build_essential_bundles_compilers_and_make():
    r = _resolver('41')
    units, _ = r.resolve_with_roots(['build-essential'])
    assert {'dnf\\gcc', 'dnf\\gcc-cpp', 'dnf\\make'} <= set(units)
    assert units['dnf\\gcc-cpp'].name == 'gcc-c++'   # +-free key, real package name


def test_vulkan_dev_routes_fedora_xcb_libs():
    r = _resolver('41')
    units, _ = r.resolve_with_roots(['vulkan-dev'])
    assert 'dnf\\libxcb-devel' in units            # bundles xinput + xinerama on Fedora
    assert 'dnf\\xcb-util-cursor-devel' in units
    assert 'tarball\\vulkan-sdk' in units           # OS-agnostic tarball, unchanged
    assert {'dnf\\gcc', 'dnf\\make'} <= set(units)  # build-essential pulled in


def test_graphics_and_dev_profiles_route_on_fedora():
    # graphics fully resolves; dev resolves its F41-available components
    r = _resolver('41')
    for name in ['vulkan-dev', 'cargo', 'build-essential', 'gcc-13', 'clang-18']:
        r.resolve_with_roots([name])   # raises ResolveError if unroutable
