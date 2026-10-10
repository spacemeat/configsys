'''Regression tests for a batch of route-DATA fixes:

* `installed-name:` accepts a driver-keyed map (like `name:`): an apt-ism (Debian's `rust-all` meta
  read via `cargo`, LibreOffice read via `libreoffice-core`) must not make pacman probe a package
  that doesn't exist on Arch. A scalar still applies to every manager.
* fedora_atomic brew names: tshark ships in brew's CLI-only `wireshark` formula, netcat's formula is
  `netcat`; libfuse2 declines on atomic (no brew formula; AppImages aren't managed there), so
  appImage methods decline instead of `brew install libfuse2`.
* pipx's `python:` pin suggestion is derived from the routes' python3 providers (incl. 3.14).
'''

import os

import pytest

from configsys.componentObj import ResolvedComponent
from configsys.drivers import get_driver
from configsys.drivers._native import installed_name
from configsys.resolve import ResolveError
from configsys.routes import Resolver

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')


def _unit(driver, name, **fields):
    return ResolvedComponent(key=f'{driver}\\{name}', driver=driver, comp=name,
                             fields={'name': name, **fields})


# -- installed-name: driver-keyed map -------------------------------------------------------------

@pytest.mark.parametrize('driver', ['dnf', 'pacman', 'zypper', 'apk', 'xbps'])
def test_apt_keyed_installed_name_leaves_other_managers_on_the_plain_name(driver):
    d = get_driver(driver, None)
    u = _unit(driver, 'rust', **{'installed-name': {'apt': 'cargo'}})
    assert d.index_key(u) == 'rust'
    assert installed_name(u) is None


def test_apt_reads_its_keyed_installed_name():
    d = get_driver('apt', None)
    u = _unit('apt', 'libreoffice', **{'installed-name': {'apt': 'libreoffice-core'}})
    assert d.index_key(u) == 'libreoffice-core'


def test_installed_name_map_default_and_scalar_back_compat():
    u = _unit('pacman', 'x', **{'installed-name': {'apt': 'a', 'default': 'd'}})
    assert get_driver('pacman', None).index_key(u) == 'd'
    for drv in ('apt', 'dnf', 'pacman', 'zypper', 'apk', 'xbps'):   # a scalar = every manager
        assert get_driver(drv, None).index_key(_unit(drv, 'x', **{'installed-name': 'y'})) == 'y'
    assert installed_name(_unit('apt', 'x', **{'installed-name': {'dnf': 'z'}}), 'dnf') == 'z'


def _own(block, version, comp):
    units = Resolver(ROUTES, block, version, 'x86_64').resolve_names([comp])
    (rc,) = [rc for rc in units.values() if rc.comp == comp]
    return rc, units


@pytest.mark.parametrize('comp, block, version, probe', [
    ('rust', 'arch', '20260101', 'rust'),                       # Arch's `rust` merely PROVIDES cargo
    ('rust', 'ubuntu', '24.04', 'cargo'),                       # rust-all meta -> read from cargo
    ('libreoffice', 'arch', '20260101', 'libreoffice-fresh'),   # no libreoffice-core on Arch
    ('libreoffice', 'ubuntu', '24.04', 'libreoffice-core'),
    ('libreoffice', 'fedora', '41', 'libreoffice-core'),        # Fedora splits the suite too
    ('ruby', 'ubuntu', '24.04', 'ruby'),                        # ruby-full meta -> read from ruby
    ('ruby', 'arch', '20260101', 'ruby'),
])
def test_routes_probe_the_right_package_per_manager(comp, block, version, probe):
    rc, _ = _own(block, version, comp)
    assert get_driver(rc.driver, None).index_key(rc) == probe


# -- fedora_atomic brew names + libfuse2 ----------------------------------------------------------

@pytest.mark.parametrize('comp, pkg', [('tshark', 'wireshark'), ('netcat', 'netcat'),
                                       ('lldb', 'lldb')])     # lldb: its own formula (needs llvm)
def test_fedora_atomic_brew_formula_names(comp, pkg):
    rc, _ = _own('fedora_atomic', '41', comp)
    assert (rc.driver, rc.name) == ('brew', pkg)


def test_libfuse2_declines_on_fedora_atomic():
    with pytest.raises(ResolveError):
        Resolver(ROUTES, 'fedora_atomic', '41', 'x86_64').resolve_names(['libfuse2'])
    rc, _ = _own('fedora', '41', 'libfuse2')                    # still native elsewhere
    assert (rc.driver, rc.name) == ('dnf', 'fuse-libs')


@pytest.mark.parametrize('comp, driver', [('neovim', 'brew'), ('arduino', 'flatpak')])
def test_appimage_apps_still_route_on_fedora_atomic_without_appimage(comp, driver):
    rc, units = _own('fedora_atomic', '41', comp)
    assert rc.driver == driver
    assert not any(u.driver == 'appImage' or u.comp == 'libfuse2' for u in units.values())


def test_neovim_appimage_not_a_candidate_on_fedora_atomic():
    r = Resolver(ROUTES, 'fedora_atomic', '41', 'x86_64')
    vias = {m['via'] for m in r.candidates('neovim')}
    assert 'appImage' not in vias and 'native' in vias


# -- pipx: python pin suggestion ------------------------------------------------------------------

def test_pipx_suggest_pin_derives_from_routes_python_providers():
    from types import SimpleNamespace
    from configsys.drivers.pipx import Pipx, _shipped_pythons
    shipped = [n for _v, n in _shipped_pythons(ROUTES)]
    assert shipped == ['python3.10', 'python3.11', 'python3.12', 'python3.13', 'python3.14']
    p = Pipx(None, SimpleNamespace(routes_file=ROUTES))
    assert p._suggest_pin('>=3.14') == 'python3.14'
    assert p._suggest_pin('>=3.12') == 'python3.12'
    assert p._suggest_pin('>=3.10') == 'python3.10'
    assert p._suggest_pin('>=3.99') is None


def test_pipx_suggest_pin_fallback_without_routes():
    from configsys.drivers.pipx import Pipx
    p = Pipx(None, None)                                        # no paths -> the fallback list
    assert p._suggest_pin('>=3.14') == 'python3.14'
    assert p._suggest_pin('>=3.10,<3.11') == 'python3.10'


def test_orphans_reverse_index_resolves_keyed_installed_name():
    from types import SimpleNamespace
    from configsys import orphans as O
    from configsys.runner import Runner
    for block, version, mgr, has, hasnt in [('ubuntu', '24.04', 'apt', 'cargo', None),
                                            ('arch', '20260101', 'pacman', 'rust', 'cargo')]:
        r = Resolver(ROUTES, block, version, 'x86_64')
        ri = O.build_reverse_index(SimpleNamespace(routes=r, runner=Runner(pretend=True), paths=None))
        assert ri.get((mgr, has)) == ['rust']
        if hasnt:                                   # the apt-keyed `cargo` doesn't leak onto Arch
            assert ri.get((mgr, hasnt)) is None


# -- AppImage-only apps on fedora_atomic: "no method here", not an unmet libfuse2 -----------------

APPIMAGE_ONLY_ON_ATOMIC = ['allusion', 'ghostty', 'dbx', 'lap', 'mediachips', 'tmog', 'video-hub-app',
                           'photocraft', 'vectorcraft', 'lightcraft', 'designcraft', 'filmcraft',
                           'effectcraft', 'pdfcraft', 'wordcraft', 'gridcraft', 'deckcraft',
                           'cadcraft', 'soundcraft']


@pytest.mark.parametrize('comp', APPIMAGE_ONLY_ON_ATOMIC)
def test_appimage_only_apps_have_no_method_on_fedora_atomic(comp):
    r = Resolver(ROUTES, 'fedora_atomic', '41', 'x86_64')
    assert 'appImage' not in {m['via'] for m in r.candidates(comp)}
    with pytest.raises(ResolveError) as e:
        r.resolve_names([comp])
    assert 'libfuse2' not in str(e.value)
    # ...and the AppImage is still the method on an ordinary glibc desktop
    u = Resolver(ROUTES, 'fedora', '41', 'x86_64').resolve_names([comp])
    assert any(rc.comp == comp for rc in u.values())


# -- homebrew: the brew driver's tool -------------------------------------------------------------

def test_brew_driver_requires_homebrew():
    r = Resolver(ROUTES, 'fedora_atomic', '41', 'x86_64')
    assert 'homebrew' in r.drivers.get('brew', [])


def test_homebrew_is_glibc_only_script_and_atomic_needs_no_curl_git():
    rc, units = _own('fedora_atomic', '41', 'homebrew')
    assert rc.driver == 'script' and set(units) == {'script\\homebrew'}   # curl/git route via brew there
    rc, units = _own('ubuntu', '24.04', 'homebrew')
    assert rc.driver == 'script' and {'apt\\curl', 'apt\\git'} <= set(units)
    for block in ('alpine', 'void_musl'):
        with pytest.raises(ResolveError):
            Resolver(ROUTES, block, None, 'x86_64').resolve_names(['homebrew'])


def test_homebrew_version_probe_finds_brew_off_path(tmp_path):
    '''uBlue images ship brew under the linuxbrew prefix, usually NOT on a non-login PATH: the probe
    must still find it (here via the per-user ~/.linuxbrew fallback, same loop as the system prefix).'''
    import re
    import subprocess
    rc, _ = _own('fedora_atomic', '41', 'homebrew')
    fake = tmp_path / '.linuxbrew' / 'bin'
    fake.mkdir(parents=True)
    (fake / 'brew').write_text('#!/bin/sh\necho "Homebrew 4.6.3"\n')
    (fake / 'brew').chmod(0o755)
    env = {'HOME': str(tmp_path), 'PATH': '/usr/bin:/bin'}
    out = subprocess.run(['bash', '-c', rc.fields['version-cmd']], env=env,
                         capture_output=True, text=True).stdout
    assert re.search(rc.fields['version-re'], out).group(1) == '4.6.3'
    empty = tmp_path / 'empty'
    empty.mkdir()
    out = subprocess.run(['bash', '-c', rc.fields['version-cmd']],
                         env={'HOME': str(empty), 'PATH': '/usr/bin:/bin'},
                         capture_output=True, text=True).stdout
    if not os.path.exists('/home/linuxbrew/.linuxbrew/bin/brew'):
        assert out.strip() == ''                    # absent -> "not installed"
