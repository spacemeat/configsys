'''RHEL-family routing against the real routes.hu: EPEL packages pull epel-release
first, versioned clang via clangNN compat packages, gcc via gcc-toolset.'''

import os

import humon
import pytest

from configsys.errors import ResolveError
from configsys.families import get_family
from configsys.routes import RouteResolver
from configsys.runner import Runner

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')


def _r():
    return RouteResolver(humon.from_file(ROUTES), 'rhel', '9.8')


def test_epel_packages_depend_on_epel_release():
    r = _r()
    for name in ['btop', 'fzf', 'ripgrep', 'xclip', 'pipx']:
        units, _ = r.resolve_with_roots([name])
        assert 'dnf\\epel-release' in units[f'dnf\\{name}'].deps


def test_base_packages_have_no_epel_dep():
    r = _r()
    units, _ = r.resolve_with_roots(['curl'])          # baseos, not EPEL
    assert units['dnf\\curl'].deps == set()


def test_el_clang_uses_compat_packages_from_epel():
    r = _r()
    units, _ = r.resolve_with_roots(['clang-20'])
    rc = units['clang\\clang-20']
    assert get_family('clang', Runner(pretend=True))._packages(rc) == ['clang20']
    assert 'dnf\\epel-release' in rc.deps


def test_clang18_not_packaged_on_el9():
    with pytest.raises(ResolveError):
        _r().resolve_with_roots(['clang-18'])


def test_gcc_stays_toolset_on_el():
    r = _r()
    assert 'gcc-toolset\\gcc-15' in r.resolve_names(['gcc-15'])


def test_apod_pulls_epel_for_its_pipx():
    r = _r()
    units, _ = r.resolve_with_roots(['apod'])
    assert 'dnf\\pipx' in units and 'dnf\\epel-release' in units
