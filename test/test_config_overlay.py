import pytest

from configsys import layers
from configsys.config import Config
from configsys.errors import ConfigError


def cfg(config_text, user_text=None):
    ls = [layers.Layer('config.hu', 'repo', layers.materialize_string(config_text))]
    if user_text is not None:
        ls.append(layers.Layer('user.hu', 'user', layers.materialize_string(user_text)))
    return Config(ls)


REPO = '''{
    configs: [ dev ]
    profiles: {
        dev: [ btop, fzf, ripgrep ]
        games: [ steam ]
    }
}'''


def test_active_profiles_from_repo_when_no_user():
    c = cfg(REPO)
    assert c.active_profiles == ['dev']
    assert c.profile_components('dev') == ['btop', 'fzf', 'ripgrep']


def test_user_overrides_configs_selection():
    c = cfg(REPO, '{ configs: [ dev, games ] }')
    assert c.active_profiles == ['dev', 'games']
    assert c.requested() == {
        'btop': ['dev'], 'fzf': ['dev'], 'ripgrep': ['dev'], 'steam': ['games'],
    }


def test_user_redefines_a_profile():
    c = cfg(REPO, '{ configs: [ dev ]  profiles: { dev: [ btop, xclip ] } }')
    assert c.profile_components('dev') == ['btop', 'xclip']


def test_user_profiles_section_shadows_per_name_not_wholesale():
    # user redefines `dev` but leaves `games` to the repo (per-name overlay, not a
    # whole-section replace).
    c = cfg(REPO, '{ configs: [ dev, games ]  profiles: { dev: [ btop ] } }')
    assert c.profile_components('dev') == ['btop']          # user's
    assert c.profile_components('games') == ['steam']       # still the repo's


def test_user_can_add_a_new_profile():
    c = cfg(REPO, '{ configs: [ mine ]  profiles: { mine: [ btop, neovim ] } }')
    assert c.profile_components('mine') == ['btop', 'neovim']


def test_single_value_configs():
    c = cfg('{ configs: dev  profiles: { dev: [ btop ] } }')
    assert c.active_profiles == ['dev']


def test_nested_profile_flattened_to_leaves():
    c = cfg('{ configs: [ dev ]  profiles: { dev: { group: [ btop, fzf ]  more: [ ripgrep ] } } }')
    assert c.profile_components('dev') == ['btop', 'fzf', 'ripgrep']


def test_selected_but_undefined_profile_errors():
    c = cfg('{ configs: [ ghost ] }')
    with pytest.raises(ConfigError):
        c.profile_components('ghost')


# -- profile composition (+include / ~remove) -----------------------------

COMPOSE = '''{
    configs: [ desktop ]
    profiles: {
        base:    [ neovim, htop, fzf ]
        dev:     [ +base, gcc-15, gdb ]
        desktop: [ +dev, steam, ~gdb ]
    }
}'''


def test_include_splices_another_profile():
    c = cfg(COMPOSE)
    assert c.profile_components('dev') == ['neovim', 'htop', 'fzf', 'gcc-15', 'gdb']


def test_include_then_remove_is_order_significant():
    # desktop = (dev = base + gcc-15 + gdb) + steam - gdb
    c = cfg(COMPOSE)
    assert c.profile_components('desktop') == ['neovim', 'htop', 'fzf', 'gcc-15', 'steam']


def test_remove_before_add_readds():
    c = cfg('{ configs: [ p ]  profiles: { p: [ ~steam, steam ] } }')
    assert c.profile_components('p') == ['steam']


def test_remove_of_absent_is_noop():
    c = cfg('{ configs: [ p ]  profiles: { p: [ btop, ~steam ] } }')
    assert c.profile_components('p') == ['btop']


def test_transitive_include_dedupes():
    c = cfg('''{ configs: [ c ]  profiles: {
        a: [ x ]
        b: [ +a, y ]
        c: [ +a, +b, z ]
    } }''')
    assert c.profile_components('c') == ['x', 'y', 'z']


def test_requested_uses_expanded_components():
    c = cfg(COMPOSE)
    req = c.requested()
    assert 'gdb' not in req                     # removed in desktop
    assert req['neovim'] == ['desktop']         # via +dev -> +base
    assert req['steam'] == ['desktop']


def test_include_cycle_raises():
    c = cfg('{ configs: [ a ]  profiles: { a: [ +b ]  b: [ +a ] } }')
    with pytest.raises(ConfigError):
        c.profile_components('a')


def test_self_include_with_no_lower_layer_errors():
    # `+a` inside `a` means "inherit the layer below" — with nothing below, that's a mistake.
    c = cfg('{ configs: [ a ]  profiles: { a: [ +a ] } }')
    with pytest.raises(ConfigError):
        c.profile_components('a')


# -- in-place amendment via +self (super semantics) -----------------------

def test_amend_inherits_lower_layer_via_self_include():
    c = cfg('{ profiles: { p: [ a, b ] } }', '{ profiles: { p: [ +p, c ] } }')
    assert c.profile_components('p') == ['a', 'b', 'c']


def test_amend_can_remove_an_inherited_member():
    c = cfg('{ profiles: { p: [ a, b ] } }', '{ profiles: { p: [ +p, ~a, c ] } }')
    assert c.profile_components('p') == ['b', 'c']


def test_bare_redefine_still_replaces_wholesale():
    c = cfg('{ profiles: { p: [ a, b ] } }', '{ profiles: { p: [ c ] } }')
    assert c.profile_components('p') == ['c']


def test_cross_profile_ref_sees_the_amended_top():
    # `dev` includes `+user`; user is amended in the top layer -> dev gets the amended set.
    c = cfg('{ profiles: { user: [ a ] } }',
            '{ profiles: { user: [ +user, b ]  dev: [ +user, c ] } }')
    assert c.profile_components('dev') == ['a', 'b', 'c']


def test_three_layer_amend_chain():
    ls = [layers.Layer('repo.hu', 'repo', layers.materialize_string('{ profiles: { p: [ a ] } }')),
          layers.Layer('plug.hu', 'plugin', layers.materialize_string('{ profiles: { p: [ +p, b ] } }')),
          layers.Layer('user.hu', 'user', layers.materialize_string('{ profiles: { p: [ +p, c ] } }'))]
    assert Config(ls).profile_components('p') == ['a', 'b', 'c']


# -- own-components (menu attribution: +self counts, +other doesn't) -------

OWN = '''{
    configs: [ user, sculpture ]
    profiles: {
        user:      [ a, b ]
        sculpture: [ +user, blender ]
    }
}'''


def test_own_components_excludes_cross_profile_include():
    c = cfg(OWN)
    assert c.profile_components('sculpture') == ['a', 'b', 'blender']   # full (for install)
    assert c.profile_own_components('sculpture') == ['blender']         # own (for the menu)


def test_own_components_includes_self_amendment():
    c = cfg('{ profiles: { user: [ a, b ] } }', '{ profiles: { user: [ +user, c ] } }')
    assert c.profile_own_components('user') == ['a', 'b', 'c']


def test_menu_profile_comps_dedupes_included_components():
    from configsys.tui.menu import _profile_comps
    comps = dict(_profile_comps(cfg(OWN)))
    assert comps['user'] == ['a', 'b']            # base profile keeps its components
    assert comps['sculpture'] == ['blender']      # included a/b now show only under `user`


def test_menu_keeps_orphan_when_owner_profile_inactive():
    # sculpture is active but `user` is NOT — its included a/b have no active owner, so they
    # stay visible under sculpture rather than vanishing (install is transitive).
    c = cfg('{ profiles: { user: [ a, b ]  sculpture: [ +user, blender ] } }',
            '{ configs: [ sculpture ] }')
    from configsys.tui.menu import _profile_comps
    comps = dict(_profile_comps(c))
    assert comps['sculpture'] == ['a', 'b', 'blender']


def test_profile_and_component_names_may_collide():
    # A profile named `blender` includes the base profile and adds the `blender` component —
    # the `+` sigil keeps the reference unambiguous, so no naming constraint is needed.
    c = cfg('''{ configs: [ blender ]  profiles: {
        base:    [ neovim ]
        blender: [ +base, blender ]
    } }''')
    assert c.profile_components('blender') == ['neovim', 'blender']


# -- primary plugin contributes machine settings (repo < primary < top config) ----

def _layers(*specs):
    return [layers.Layer(f'{role}.hu', role, layers.materialize_string(text)) for role, text in specs]


def test_primary_plugin_sets_configs_scope_pins():
    c = Config(_layers(
        ('repo', '{ configs: [ base ]  profiles: { base: [ a ]  sculpt: [ b ] } }'),
        ('primary', '{ configs: [ base, sculpt ]  scope: system  pins: { steam: flatpak } }'),
        ('user', '{ }')))
    assert c.active_profiles == ['base', 'sculpt']     # primary's configs applied
    assert c.default_scope() == 'system'
    assert c.pins() == {'steam': 'flatpak'}


def test_top_config_overrides_primary():
    c = Config(_layers(
        ('repo', '{ profiles: { base: [ a ]  sculpt: [ b ] } }'),
        ('primary', '{ configs: [ base, sculpt ]  scope: system }'),
        ('user', '{ configs: [ base ]  scope: user }')))
    assert c.active_profiles == ['base']               # top config wins
    assert c.default_scope() == 'user'


def test_ordinary_plugin_role_cannot_set_machine_settings():
    c = Config(_layers(
        ('repo', '{ configs: [ base ]  profiles: { base: [ a ]  sculpt: [ b ] } }'),
        ('plugin', '{ configs: [ base, sculpt ]  scope: system }'),   # ignored (not primary)
        ('user', '{ }')))
    assert c.active_profiles == ['base']               # plugin configs ignored
    assert c.default_scope() is None


def test_default_scope_absent_is_none():
    assert cfg(REPO).default_scope() is None


def test_default_scope_from_user_config():
    c = cfg(REPO, '{ configs: [ dev ]  scope: system }')
    assert c.default_scope() == 'system'


def test_overlap_across_profiles_tracks_all_requesters():
    c = cfg('{ configs: [ a, b ]  profiles: { a: [ ripgrep ]  b: [ ripgrep, btop ] } }')
    req = c.requested()
    assert req['ripgrep'] == ['a', 'b']
    assert req['btop'] == ['b']


def test_pins_absent_is_empty():
    assert cfg(REPO).pins() == {}


def test_pins_from_user_file():
    c = cfg(REPO, '{ configs: [ dev ]  pins: { steam: flatpak  cc: clang-18 } }')
    assert c.pins() == {'steam': 'flatpak', 'cc': 'clang-18'}
