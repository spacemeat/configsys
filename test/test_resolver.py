from pathlib import Path

import pytest

from configsys.errors import ResolveError
from configsys.routes import RouteResolver
from configsys.troveio import load


def resolver(os_block='pop_os!'):
    routes = Path(__file__).resolve().parent.parent / 'routes.hu'
    return RouteResolver(load(routes), os_block)


def test_indirect_dict_package_binding():
    units = resolver().resolve_names(['vulkan-dev'])
    assert set(units) == {'apt\\vulkan-sdk'}
    u = units['apt\\vulkan-sdk']
    assert u.fields['name'] == 'vulkan-sdk'
    assert u.fields['source-path'] == '/etc/apt/sources.list.d/lunarg-vulkan-jammy.list'


def test_list_route_expands_to_all_parts():
    units = resolver().resolve_names(['neovim'])
    # neovim -> [appImage\neovim, neovim-config -> [ripgrep, dotfiles\neovim]]
    assert set(units) == {'appImage\\neovim', 'apt\\ripgrep', 'dotfiles\\neovim'}


def test_dedup_across_standalone_and_dependency():
    # ripgrep is both a standalone dev component and pulled in via neovim-config
    units = resolver().resolve_names(['ripgrep', 'neovim'])
    assert 'apt\\ripgrep' in units
    # one unit, but recorded as requested by both entry points
    assert units['apt\\ripgrep'].requested_as == {'ripgrep', 'neovim'}


def test_font_var_substitution():
    units = resolver().resolve_names(['mononoki-nerd'])
    u = units['debian-font\\mononoki-nerd']
    assert u.family == 'debian-font'
    # $FONTDIR = ~/.local/share/fonts/$FONTNAME-$FONTVERSION resolves via comp vars
    assert u.vars['$FONTDIR'] == '~/.local/share/fonts/mononoki-nerd-v3.1.1'
    assert u.vars['$FONTURLL'].endswith('/v3.1.1/Mononoki.zip')


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
        'apt\\vulkan-sdk', 'appImage\\neovim', 'apt\\ripgrep', 'dotfiles\\neovim',
        'flatpak\\firefox', 'flatpak\\chrome', 'appImage\\arduino', 'apt\\btop',
        'apt\\fzf', 'apt\\xclip', 'apt\\cargo', 'apt\\build-essential',
        'debian-font\\mononoki-nerd',
    }
    assert set(units) == expected
