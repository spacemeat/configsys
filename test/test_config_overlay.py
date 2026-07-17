import humon as h
import pytest

from configsys.config import Config
from configsys.errors import ConfigError


def cfg(config_text, user_text=None):
    ct = h.from_string(config_text)
    ut = h.from_string(user_text) if user_text is not None else None
    return Config(ct, ut)


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
