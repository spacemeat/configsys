'''suggests: — soft (optional) dependencies. Pulled in if resolvable in the loaded layers,
skipped silently if not — unlike requires:, which errors when unmet. This is the package ->
personal-config edge: base declares "I'd like my dotfiles", and they attach only when a layer
(e.g. a user's configsys-user plugin) actually supplies them.'''

import pytest

from configsys.resolve import ResolveError
from configsys.routes import Resolver

OS = 'os: { linux: {}  debian: { using: linux  native: apt } }'


def _units(tmp_path, components, names, block='debian', version='12'):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  components: { ' + components + ' } }')
    return Resolver(str(p), block, version).resolve_names(names)


def test_suggests_pulls_when_a_provider_is_present(tmp_path):
    comps = '''
        editor:     { requires: libc  suggests: editor-cfg  install: [ { via: native } ] }
        libc:       { install: [ { via: native } ] }
        editor-cfg: { install: [ { via: dotfiles  src: e  dst: ~/e } ] }
    '''
    assert set(_units(tmp_path, comps, ['editor'])) == {
        'apt\\editor', 'apt\\libc', 'dotfiles\\editor-cfg'}


def test_suggests_skipped_when_absent_without_error(tmp_path):
    comps = 'gadget: { suggests: missing-cfg  install: [ { via: native } ] }'
    assert set(_units(tmp_path, comps, ['gadget'])) == {'apt\\gadget'}    # skipped, not an error


def test_requires_still_errors_when_absent(tmp_path):
    comps = 'broken: { requires: nonexistent  install: [ { via: native } ] }'
    with pytest.raises(ResolveError):
        _units(tmp_path, comps, ['broken'])


def test_suggests_a_capability(tmp_path):
    with_provider = '''
        printer:   { suggests: ink  install: [ { via: native } ] }
        cartridge: { provides: ink  install: [ { via: native } ] }
    '''
    assert set(_units(tmp_path, with_provider, ['printer'])) == {'apt\\printer', 'apt\\cartridge'}
    without = 'printer: { suggests: ink  install: [ { via: native } ] }'
    assert set(_units(tmp_path, without, ['printer'])) == {'apt\\printer'}


def test_a_suggested_components_own_requires_stay_hard(tmp_path):
    # pulling a suggested component enforces ITS hard requires (soft is only the edge)
    ok = '''
        app:    { suggests: appcfg  install: [ { via: native } ] }
        appcfg: { requires: appdep  install: [ { via: native } ] }
        appdep: { install: [ { via: native } ] }
    '''
    assert set(_units(tmp_path, ok, ['app'])) == {'apt\\app', 'apt\\appcfg', 'apt\\appdep'}
    # drop appdep: the suggest still pulls appcfg, whose now-unmet HARD requires errors
    broken = '''
        app:    { suggests: appcfg  install: [ { via: native } ] }
        appcfg: { requires: appdep  install: [ { via: native } ] }
    '''
    with pytest.raises(ResolveError):
        _units(tmp_path, broken, ['app'])


def test_binding_level_suggests_and_no_field_leak(tmp_path):
    comps = '''
        tool:     { install: [ { via: native  suggests: tool-cfg } ] }
        tool-cfg: { install: [ { via: dotfiles  src: t  dst: ~/t } ] }
    '''
    units = _units(tmp_path, comps, ['tool'])
    assert set(units) == {'apt\\tool', 'dotfiles\\tool-cfg'}
    assert 'suggests' not in units['apt\\tool'].fields       # steers resolution, not install


def test_suggested_dotfile_rides_only_with_its_package(tmp_path):
    # the whole point: define the config, but it activates only when its package is in the set
    comps = '''
        neovim:         { suggests: neovim-dotfiles  install: [ { via: native } ] }
        neovim-dotfiles:{ install: [ { via: dotfiles  src: nvim  dst: ~/.config/nvim } ] }
        htop:           { install: [ { via: native } ] }
    '''
    assert 'dotfiles\\neovim-dotfiles' in set(_units(tmp_path, comps, ['neovim']))
    assert set(_units(tmp_path, comps, ['htop'])) == {'apt\\htop'}   # nvim cfg not dragged in
