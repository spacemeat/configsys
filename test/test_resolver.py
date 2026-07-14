from pathlib import Path

import pytest

from configsys.errors import ResolveError
from configsys.routes import RouteResolver
from configsys.troveio import load


def resolver(os_block='pop_os!'):
    routes = Path(__file__).resolve().parent.parent / 'routes.hu'
    return RouteResolver(load(routes), os_block)


def test_indirect_dict_package_binding_inline():
    # The `{ package: fam\comp }` indirection is still supported by the resolver
    # (validated with an inline trove, independent of routes.hu content).
    import humon as h
    from configsys.routes import RouteResolver
    routes = h.from_string(
        '{ \\apt: { thing: { name: the-thing } }'
        '  linux: {}'
        '  debian: { !using: linux  *: apt\\*  widget: { package: apt\\thing } } }')
    units = RouteResolver(routes, 'debian').resolve_names(['widget'])
    assert set(units) == {'apt\\thing'}
    assert units['apt\\thing'].fields['name'] == 'the-thing'


def test_vulkan_dev_composite_pulls_xcb_build_and_tarball():
    units = resolver().resolve_names(['vulkan-dev'])
    assert set(units) == {
        'apt\\libxcb-xinput0', 'apt\\libxcb-xinerama0', 'apt\\libxcb-cursor-dev',
        'apt\\build-essential', 'tarball\\vulkan-sdk',
        'apt\\curl',  # tarball family !depends
    }
    assert units['tarball\\vulkan-sdk'].deps == {'apt\\curl'}


def test_vulkan_sdk_resolves_to_tarball_with_version_spec():
    units = resolver().resolve_names(['vulkan-sdk'])
    u = units['tarball\\vulkan-sdk']
    assert u.family == 'tarball'
    assert u.fields['version'] == {'static': '1.4.350.1'}  # discovery spec, not literal
    assert u.fields['installDir'] == 'vulkan'
    # $VERSION stays literal in the route; the family substitutes at install time
    assert '$VERSION' in u.fields['url']


def test_appimage_version_is_a_github_spec_with_asset():
    u = resolver().resolve_names(['neovim'])['appImage\\neovim']
    assert u.fields['version']['github'] == 'neovim/neovim'
    assert u.fields['version']['asset'] == 'nvim-linux-$ARCH.appimage'  # arch-aware glob
    assert '$VERSION' in u.fields['url'] and '$ARCH' in u.fields['url']


def test_list_route_expands_to_all_parts():
    units = resolver().resolve_names(['neovim'])
    # neovim -> [appImage\neovim, neovim-config -> [ripgrep, dotfiles\neovim]]
    # plus appImage's family !depends (apt\libfuse2)
    assert set(units) == {'appImage\\neovim', 'apt\\ripgrep', 'dotfiles\\neovim',
                          'apt\\libfuse2'}
    assert units['appImage\\neovim'].deps == {'apt\\libfuse2'}


def test_dedup_across_standalone_and_dependency():
    # ripgrep is both a standalone dev component and pulled in via neovim-config
    units = resolver().resolve_names(['ripgrep', 'neovim'])
    assert 'apt\\ripgrep' in units
    # one unit, but recorded as requested by both entry points
    assert units['apt\\ripgrep'].requested_as == {'ripgrep', 'neovim'}


def test_font_resolves_with_version_spec_and_deps():
    units = resolver().resolve_names(['mononoki-nerd'])
    u = units['debian-font\\mononoki-nerd']
    assert u.family == 'debian-font'
    assert u.fields['version']['github'] == 'ryanoasis/nerd-fonts'
    assert u.fields['version']['asset'] == 'Mononoki.zip'
    assert '$VERSION' in u.fields['url'] and u.fields['url'].endswith('Mononoki.zip')
    assert u.deps == {'apt\\fontconfig', 'apt\\unzip'}   # !depends resolved


def test_unroutable_name_raises_resolveerror():
    # A bare name with no explicit route flows through *: apt\* -> apt\<name>,
    # which fails cleanly when the apt family has no such node (no silent success).
    with pytest.raises(ResolveError) as ei:
        resolver().resolve_names(['definitely-not-a-package'])
    assert 'definitely-not-a-package' in str(ei.value)
    assert 'apt' in str(ei.value)


def test_full_dev_profile_resolves():
    names = ['vulkan-dev', 'neovim', 'firefox', 'chrome', 'arduino', 'btop',
             'fzf', 'ripgrep', 'xclip', 'cargo', 'build-essential', 'mononoki-nerd']
    units = resolver().resolve_names(names)
    expected = {
        # vulkan-dev composite
        'apt\\libxcb-xinput0', 'apt\\libxcb-xinerama0', 'apt\\libxcb-cursor-dev',
        'apt\\build-essential', 'tarball\\vulkan-sdk',
        # neovim composite
        'appImage\\neovim', 'apt\\ripgrep', 'dotfiles\\neovim',
        # singletons
        'flatpak\\firefox', 'flatpak\\chrome', 'appImage\\arduino', 'apt\\btop',
        'apt\\fzf', 'apt\\xclip', 'apt\\cargo', 'debian-font\\mononoki-nerd',
        # family !depends auto-added
        'apt\\flatpak', 'apt\\curl', 'apt\\libfuse2',
        'apt\\fontconfig', 'apt\\unzip',
    }
    assert set(units) == expected
