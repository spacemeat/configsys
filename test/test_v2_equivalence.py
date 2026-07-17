'''Equivalence harness: resolve the same components with the OLD RouteResolver and the
NEW v2 resolver across contexts, and assert they match. This is the gate for porting a
component — the diff must be empty before the new engine takes over.

Two levels:
  * primary unit   — (mechanism, component, package) of the requested component
  * full closure   — the whole set of resolved unit keys (deps included), plus
                     requested_as attribution for reuse.
'''

import os

import humon
import pytest

from configsys.routes import RouteResolver
from configsys.v2 import routes2
from configsys.v2.resolve import resolve, resolve_one

HERE = os.path.dirname(__file__)
ROUTES1 = os.path.join(HERE, '..', 'routes.hu')
ROUTES2 = os.path.join(HERE, '..', 'routes2.hu')


def _old(block, version):
    return RouteResolver(humon.from_file(ROUTES1), block, version)


def _v2():
    return routes2.load(ROUTES2)


# -- primary-unit equivalence ---------------------------------------------

PRIMARY = [
    ('btop', 'ubuntu', '24.04'), ('btop', 'fedora', '41'), ('btop', 'arch', '20260101'),
    ('libfuse2', 'fedora', '41'), ('libfuse2', 'arch', '20260101'),
    ('chrome', 'ubuntu', '24.04'),
    ('steam', 'pop_os!', '22.04'), ('steam', 'ubuntu', '24.04'),
]


@pytest.mark.parametrize('comp,block,version', PRIMARY)
def test_primary_unit_matches(comp, block, version):
    units = _old(block, version).resolve_names([comp])
    old = next((rc.family, rc.comp, rc.fields.get('name'))
               for rc in units.values() if rc.comp == comp)
    cascade, components, _ = _v2()
    new = resolve_one(comp, cascade, components, block, version, 'x86_64').as_tuple()
    assert new == old


# -- full-closure equivalence ---------------------------------------------

CLOSURE = [
    ('btop', 'ubuntu', '24.04'),
    ('chrome', 'ubuntu', '24.04'), ('chrome', 'fedora', '41'), ('chrome', 'arch', '20260101'),
    ('tree-sitter-cli', 'ubuntu', '24.04'), ('tree-sitter-cli', 'arch', '20260101'),
    ('mononoki-nerd', 'ubuntu', '24.04'), ('mononoki-nerd', 'fedora', '41'),
    ('steam', 'pop_os!', '22.04'),          # native, no deps
    ('steam', 'ubuntu', '24.04'),           # flatpak -> pulls the flatpak tool
    ('libfuse2', 'arch', '20260101'),
    # fetch-artifact + dotfiles chain
    ('neovim', 'ubuntu', '24.04'), ('neovim', 'fedora', '41'), ('neovim', 'arch', '20260101'),
    ('arduino', 'ubuntu', '24.04'),
    # github .deb / native per OS
    ('fastfetch', 'ubuntu', '24.04'), ('fastfetch', 'fedora', '41'), ('fastfetch', 'arch', '20260101'),
    # version-variant collapse: pipx bootstraps via pip on old Ubuntu/Debian, native elsewhere
    ('pipx', 'ubuntu', '24.04'), ('pipx', 'ubuntu', '22.04'),
    ('pipx', 'debian', '12'), ('pipx', 'debian', '11'),
    ('pipx', 'fedora', '41'), ('pipx', 'arch', '20260101'),
    # EPEL capability: only pulls epel-release on EL, a no-op elsewhere
    ('btop', 'debian', '12'), ('btop', 'fedora', '41'),
    ('btop', 'rhel', '9.8'), ('btop', 'arch', '20260101'),
    ('pipx', 'rhel', '9.8'),                 # native pipx + EPEL
    # parts: composition — the aggregator has no unit, just its (per-OS) parts
    ('vulkan-runtime', 'ubuntu', '24.04'),
    ('vulkan-runtime', 'fedora', '41'),
    ('vulkan-runtime', 'arch', '20260101'),
    ('vulkan-runtime', 'rhel', '9.8'),       # redhat binding covers EL
    # versioned gcc: apt PPA + alternatives (Debian), dnf compat (Fedora, per-release),
    # gcc-toolset SCL (EL)
    ('gcc-13', 'ubuntu', '24.04'), ('gcc-13', 'fedora', '41'), ('gcc-13', 'rhel', '9.8'),
    ('gcc-14', 'ubuntu', '24.04'), ('gcc-14', 'fedora', '42'), ('gcc-14', 'rhel', '9.8'),
    ('gcc-15', 'ubuntu', '24.04'), ('gcc-15', 'rhel', '9.8'),
    # versioned clang: apt.llvm.org + alternatives (Debian), dnf compat per-release
    # (Fedora), dnf compat + EPEL (EL)
    ('clang-18', 'ubuntu', '24.04'), ('clang-18', 'fedora', '41'), ('clang-18', 'fedora', '42'),
    ('clang-19', 'ubuntu', '24.04'), ('clang-19', 'fedora', '41'), ('clang-19', 'fedora', '42'),
    ('clang-19', 'rhel', '9.8'),
    ('clang-20', 'ubuntu', '24.04'), ('clang-20', 'fedora', '42'), ('clang-20', 'rhel', '9.8'),
    # tarball + composition: the SDK (tarball + inline dotfile) and the vulkan-dev bundle
    ('vulkan-sdk', 'ubuntu', '24.04'),
    ('vulkan-dev', 'ubuntu', '24.04'),
    # gcc name blocker: build-essential is one package on Debian, a compilers+make parts
    # bundle on Fedora/Arch; the `gcc` component is the alias dotfile on Debian and the
    # native package on Fedora/Arch (never both in one context).
    ('build-essential', 'ubuntu', '24.04'),
    ('build-essential', 'fedora', '41'), ('build-essential', 'arch', '20260101'),
    ('gcc', 'fedora', '41'), ('gcc', 'arch', '20260101'),
    # vulkan-dev now composes on Fedora/EL/Arch (was Debian-only, blocked on gcc)
    ('vulkan-dev', 'fedora', '41'), ('vulkan-dev', 'rhel', '9.8'),
    ('vulkan-dev', 'arch', '20260101'),
    # apod: pipx-app + dotfile. The `via: pipx` dep pulls the pipx TOOL, which is itself
    # the version-variant component — so apod's closure changes shape per context:
    # native pipx (new Ubuntu/Fedora/Arch), pip-bootstrap (old Ubuntu/Debian), +EPEL (EL).
    ('apod', 'ubuntu', '24.04'), ('apod', 'ubuntu', '22.04'),
    ('apod', 'debian', '11'), ('apod', 'fedora', '41'),
    ('apod', 'rhel', '9.8'), ('apod', 'arch', '20260101'),
    # AUR (Arch only): yay built from PKGBUILD; the `aur` mechanism pulls base-devel + git.
    ('yay', 'arch', '20260101'),
    # leftover natives — plain everywhere, but EL keeps most in EPEL (firefox is base-repo).
    ('fzf', 'ubuntu', '24.04'), ('fzf', 'fedora', '41'), ('fzf', 'rhel', '9.8'), ('fzf', 'arch', '20260101'),
    ('xclip', 'ubuntu', '24.04'), ('xclip', 'rhel', '9.8'), ('xclip', 'arch', '20260101'),
    ('firefox', 'ubuntu', '24.04'), ('firefox', 'fedora', '41'), ('firefox', 'rhel', '9.8'), ('firefox', 'arch', '20260101'),
    # EL-EPEL gaps closed for the already-ported ripgrep + fastfetch
    ('ripgrep', 'rhel', '9.8'), ('fastfetch', 'rhel', '9.8'),
]


@pytest.mark.parametrize('comp,block,version', CLOSURE)
def test_closure_matches(comp, block, version):
    old = set(_old(block, version).resolve_names([comp]))
    cascade, components, mechanisms = _v2()
    new = set(resolve([comp], cascade, components, mechanisms, block, version, 'x86_64'))
    assert new == old


# -- reuse + attribution --------------------------------------------------

def test_reuse_and_requested_as():
    # chrome and steam both go flatpak on Ubuntu; the flatpak tool resolves ONCE and is
    # attributed to both roots.
    old = _old('ubuntu', '24.04').resolve_names(['chrome', 'steam'])
    cascade, components, mechanisms = _v2()
    new = resolve(['chrome', 'steam'], cascade, components, mechanisms, 'ubuntu', '24.04', 'x86_64')

    assert set(new) == set(old)
    assert new['apt\\flatpak'].requested_as == {'chrome', 'steam'}
    assert new['apt\\flatpak'].requested_as == old['apt\\flatpak'].requested_as


def test_shared_dotfile_attributed_to_both_apps():
    # neovim and arduino both pull the bashDotD dotfile (via their own dotfiles); it
    # resolves once, attributed to both, exactly like the old resolver.
    old = _old('ubuntu', '24.04').resolve_names(['neovim', 'arduino'])
    cascade, components, mechanisms = _v2()
    new = resolve(['neovim', 'arduino'], cascade, components, mechanisms, 'ubuntu', '24.04', 'x86_64')
    assert set(new) == set(old)
    assert new['dotfiles\\bashDotD'].requested_as == {'neovim', 'arduino'}
    assert new['dotfiles\\bashDotD'].requested_as == old['dotfiles\\bashDotD'].requested_as


# -- pins (per-machine control, top of precedence) ------------------------

def test_binding_pin_forces_method():
    cascade, components, mechanisms = _v2()
    # steam on Pop is native by default...
    default = resolve(['steam'], cascade, components, mechanisms, 'pop_os!', '22.04', 'x86_64')
    assert 'apt\\steam' in default and 'flatpak\\steam' not in default
    # ...pinned to flatpak, it becomes flatpak (+ the flatpak tool), overriding the default
    pinned = resolve(['steam'], cascade, components, mechanisms, 'pop_os!', '22.04', 'x86_64',
                     pins={'steam': 'flatpak'})
    assert 'flatpak\\steam' in pinned and 'apt\\steam' not in pinned
    assert 'apt\\flatpak' in pinned


def test_provider_pin_disambiguates():
    from configsys.v2.resolve import ResolveError
    from configsys.v2.routes2 import Component
    cascade, _c, mechanisms = _v2()
    comps = {
        'toolchain': Component('toolchain', {'requires': 'cc', 'install': [{'via': 'native'}]}),
        'gccish':    Component('gccish', {'provides': 'cc', 'install': [{'via': 'native'}]}),
        'clangish':  Component('clangish', {'provides': 'cc', 'install': [{'via': 'native'}]}),
    }
    # two providers of `cc`, no pin -> ambiguous
    with pytest.raises(ResolveError):
        resolve(['toolchain'], cascade, comps, mechanisms, 'ubuntu', '24.04', 'x86_64')
    # provider-pin picks one
    units = resolve(['toolchain'], cascade, comps, mechanisms, 'ubuntu', '24.04', 'x86_64',
                    pins={'cc': 'clangish'})
    assert 'apt\\clangish' in units and 'apt\\gccish' not in units


# -- cpu-keyed asset selection (a NEW v2 capability; old hardcoded amd64) --

def test_cpu_keyed_asset_selection():
    from configsys.v2.resolve import resolve_asset, select_binding
    cascade, components, _ = _v2()
    ff = components['fastfetch']

    # on Debian, the deb binding picks the arch-correct asset
    deb = select_binding(ff, cascade, cascade.context('debian', '12', 'x86_64'))
    assert resolve_asset(deb, 'x86_64') == 'fastfetch-linux-amd64.deb'
    assert resolve_asset(deb, 'aarch64') == 'fastfetch-linux-aarch64.deb'

    # appImage $ARCH substitution
    nv = select_binding(components['neovim'], cascade, cascade.context('ubuntu', '24.04', 'aarch64'))
    assert resolve_asset(nv, 'aarch64') == 'nvim-linux-aarch64.appimage'
