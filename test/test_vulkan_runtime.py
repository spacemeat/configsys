'''vulkan-runtime routes to the loader + mesa ICDs on every distro family, is pulled
into vulkan-dev, and is in the user profile (ensure-present on every machine).'''

import os

import humon

from configsys.routes import RouteResolver

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')
CONFIG = os.path.join(os.path.dirname(__file__), '..', 'config.hu')


def _names(block, ver, comp):
    return sorted(RouteResolver(humon.from_file(ROUTES), block, ver).resolve_names([comp]))


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
        units = RouteResolver(humon.from_file(ROUTES), block, ver).resolve_names(['vulkan-dev'])
        assert any('mesa-vulkan-drivers' in k for k in units)


def test_user_profile_includes_vulkan_runtime():
    cfg = humon.from_file(CONFIG)
    user = cfg.root['user']
    names = [user[i].value for i in range(user.num_children)]
    assert 'vulkan-runtime' in names
