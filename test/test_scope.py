import argparse

from configsys.app import Context
from configsys.componentObj import ResolvedComponent
from configsys.families import get_family
from configsys.runner import Runner


def unit(family, comp='x', **fields):
    fields.setdefault('name', comp)
    return ResolvedComponent(key=f'{family}\\{comp}', family=family, comp=comp, fields=fields)


def test_fixed_scope_families():
    r = Runner(pretend=True)
    assert get_family('apt', r).scope(unit('apt')) == 'system'      # always system
    assert get_family('cargo', r).scope(unit('cargo')) == 'user'    # ~/.cargo
    assert get_family('dotfiles', r).scope(unit('dotfiles')) == 'user'
    assert not get_family('apt', r).honors_scope
    assert not get_family('cargo', r).honors_scope


def test_apt_ignores_a_scope_field():
    # a fixed-scope family reports its scope regardless of any field
    assert get_family('apt', Runner(pretend=True)).scope(unit('apt', scope='user')) == 'system'


def test_honoring_families_take_field_then_default():
    fp = get_family('flatpak', Runner(pretend=True))
    assert fp.honors_scope is True
    assert fp.scope(unit('flatpak')) == 'user'                     # family default
    assert fp.scope(unit('flatpak', scope='system')) == 'system'   # field wins


def test_machine_default_only_stamps_scope_honoring_families(tmp_path):
    (tmp_path / 'configsys.hu').write_text('{ configs: [ dev ]  scope: system }')
    args = argparse.Namespace(pretend=True, os='pop', home=str(tmp_path), config=None)
    ctx = Context(args)
    units = ctx.apply_scope_default(ctx.routes.resolve_names(['arduino', 'neovim', 'btop']))
    # honoring family with no route scope -> stamped with the machine default
    assert units['appImage\\arduino'].fields.get('scope') == 'system'
    # a route that pins scope wins over the machine default
    assert units['appImage\\neovim'].fields.get('scope') == 'user'
    # fixed-scope families are never stamped
    assert 'scope' not in units['cargo\\tree-sitter-cli'].fields
    assert 'scope' not in units['dotfiles\\neovim'].fields
    assert 'scope' not in units['apt\\btop'].fields
