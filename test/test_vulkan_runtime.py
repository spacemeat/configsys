'''vulkan-runtime routes to the loader + mesa ICDs on every distro driver, is pulled
into vulkan-dev, and is in the user profile (ensure-present on every machine).'''

import os

import humon

from configsys.routes import Resolver

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')
CONFIG = os.path.join(os.path.dirname(__file__), '..', 'config.hu')


def _names(block, ver, comp):
    return sorted(Resolver(ROUTES, block, ver).resolve_names([comp]))


def test_vulkan_runtime_per_distro():
    assert _names('ubuntu', '24.04', 'vulkan-runtime') == \
        ['apt\\libvulkan1', 'apt\\mesa-vulkan-drivers']
    assert _names('fedora', '41', 'vulkan-runtime') == \
        ['dnf\\mesa-vulkan-drivers', 'dnf\\vulkan-loader']
    assert _names('rhel', '9.8', 'vulkan-runtime') == \
        ['dnf\\mesa-vulkan-drivers', 'dnf\\vulkan-loader']   # inherited from fedora, AppStream
    assert set(_names('arch', '20260712', 'vulkan-runtime')) == {
        'pacman\\vulkan-icd-loader', 'pacman\\vulkan-radeon',
        'pacman\\vulkan-intel', 'pacman\\vulkan-swrast'}


def test_vulkan_dev_pulls_the_runtime():
    for block, ver in [('ubuntu', '24.04'), ('fedora', '41')]:
        units = Resolver(ROUTES, block, ver).resolve_names(['vulkan-dev'])
        assert any('mesa-vulkan-drivers' in k for k in units)


def test_gaming_profile_includes_vulkan_runtime():
    cfg = humon.from_file(CONFIG)
    gaming = cfg.root['profiles']['gaming']
    names = [gaming[i].value for i in range(gaming.num_children)]
    assert 'vulkan-runtime' in names


def test_vulkan_dev_resolves_on_arch():
    # the graphics profile resolves on Arch: X libs collapse to libxcb + xcb-util-cursor,
    # cpp-toolchain (-> gcc, which bundles g++) + make, plus runtime + the sdk tarball
    units = Resolver(ROUTES, 'arch', '20260712').resolve_names(['vulkan-dev'])
    for key in ('pacman\\libxcb', 'pacman\\xcb-util-cursor', 'pacman\\cpp-toolchain',
                'pacman\\make', 'pacman\\vulkan-icd-loader', 'tarball\\vulkan-sdk'):
        assert key in units
    assert units['pacman\\cpp-toolchain'].name == 'gcc'      # arch gcc bundles g++


def test_cpp_toolchain_portable():
    # `cxx` (a C++ compiler) resolves on every family — the portable replacement for the old
    # apt-named build-essential; on Arch gcc bundles g++, Debian uses g++, Alpine build-base.
    def cxx(blk, ver, drv):
        return Resolver(ROUTES, blk, ver, 'x86_64').resolve_names(['cpp-toolchain'])[f'{drv}\\cpp-toolchain'].name
    assert cxx('arch', '20260712', 'pacman') == 'gcc'
    assert cxx('ubuntu', '24.04', 'apt') == 'g++'
    assert cxx('fedora', '42', 'dnf') == 'gcc-c++'
    assert cxx('alpine', '3.20', 'apk') == 'build-base'
