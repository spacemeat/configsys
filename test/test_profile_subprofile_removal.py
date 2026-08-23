'''`~subprofile` in the profile term-algebra: a `~name` term whose name is a DEFINED profile
subtracts that whole profile's expanded member set (order-sensitive, mirroring `~component`),
so an extension profile can take a SUBSET of an included meta-profile's subprofiles.'''

import pytest

from configsys import layers
from configsys.config import Config


REPO = '''{
    configs: [ base ]
    profiles: {
        python-lang: [ python3  pip  shared ]
        ruby-lang:   [ ruby  gem  shared ]
        go-lang:     [ go ]
        jvm-lang:    [ +java-lang  +kotlin-lang ]
        java-lang:   [ jdk ]
        kotlin-lang: [ kotlin ]
        languages:   [ +python-lang  +ruby-lang  +go-lang  +jvm-lang  make ]
        base:        [ +languages ]
    }
}'''


def cfg(user_text):
    ls = [layers.Layer('config.hu', 'repo', layers.materialize_string(REPO)),
          layers.Layer('user.hu', 'user', layers.materialize_string(user_text))]
    return Config(ls)


def test_exclude_one_subprofile_drops_its_members():
    c = cfg('{ configs: [ ts ]  profiles: { ts: [ +languages  ~go-lang ] } }')
    m = c.profile_components('ts')
    assert 'go' not in m
    assert {'python3', 'pip', 'ruby', 'gem', 'make'} <= set(m)


def test_exclude_multiple_subprofiles():
    c = cfg('{ configs: [ ts ]  profiles: { ts: [ +languages  ~ruby-lang  ~jvm-lang ] } }')
    m = c.profile_components('ts')
    assert not ({'ruby', 'gem', 'jdk', 'kotlin'} & set(m))
    assert {'python3', 'pip', 'go', 'make'} <= set(m)


def test_exclude_a_nested_meta_subprofile_drops_its_transitive_members():
    # jvm-lang itself includes java-lang + kotlin-lang; excluding it drops the whole subtree.
    c = cfg('{ configs: [ ts ]  profiles: { ts: [ +languages  ~jvm-lang ] } }')
    m = c.profile_components('ts')
    assert 'jdk' not in m and 'kotlin' not in m


def test_shared_component_is_subtracted_order_sensitively():
    # `shared` is in BOTH python-lang and ruby-lang. `~ruby-lang` subtracts ruby-lang's whole set,
    # which INCLUDES `shared` -> it's dropped even though python-lang also lists it. This mirrors
    # `~component`'s order-sensitive removal; re-add explicitly to keep it (see next test).
    c = cfg('{ configs: [ ts ]  profiles: { ts: [ +languages  ~ruby-lang ] } }')
    assert 'shared' not in c.profile_components('ts')


def test_readd_after_exclude():
    c = cfg('{ configs: [ ts ]  profiles: { ts: [ +languages  ~ruby-lang  shared ] } }')
    m = c.profile_components('ts')
    assert 'shared' in m                      # a later bare add re-adds it
    assert 'ruby' not in m


def test_exclude_then_reinclude_via_a_later_plus():
    # order matters: `~ruby-lang` then `+ruby-lang` brings it back.
    c = cfg('{ configs: [ ts ]  profiles: { ts: [ +languages  ~ruby-lang  +ruby-lang ] } }')
    assert {'ruby', 'gem'} <= set(c.profile_components('ts'))


def test_bare_component_removal_still_works():
    c = cfg('{ configs: [ ts ]  profiles: { ts: [ +languages  ~make ] } }')
    assert 'make' not in c.profile_components('ts')


def test_removing_undefined_name_is_a_noop():
    # neither a defined profile nor (necessarily) a present component -> removes nothing, no error.
    c = cfg('{ configs: [ ts ]  profiles: { ts: [ +languages  ~haskel-lang ] } }')
    assert {'python3', 'ruby', 'go', 'make'} <= set(c.profile_components('ts'))


def test_layout_emits_exclude_marker_for_subprofile():
    c = cfg('{ configs: [ ts ]  profiles: { ts: [ +languages  ~ruby-lang  ~make ] } }')
    layout = c.profile_layout('ts')
    assert ('include', 'languages') in layout
    assert ('exclude', 'ruby-lang') in layout
    # ~make is a component removal, not an exclude marker (and make isn't a direct own component here)
    assert ('exclude', 'make') not in layout


def test_profile_excludes_lists_removed_subprofiles_only():
    c = cfg('{ configs: [ ts ]  profiles: { ts: [ +languages  ~ruby-lang  ~make  ~haskel-lang ] } }')
    assert c.profile_excludes('ts') == {'ruby-lang'}       # make=component, haskel-lang=undefined


def test_profile_removed_expands_subprofile_members():
    c = cfg('{ configs: [ ts ]  profiles: { ts: [ +languages  ~go-lang ] } }')
    assert 'go' in c.profile_removed('ts')


def test_profile_removal_terms_are_raw_and_unclassified():
    c = cfg('{ configs: [ ts ]  profiles: { ts: [ +languages  ~ruby-lang  ~make  ~haskel-lang ] } }')
    assert sorted(c.profile_removal_terms('ts')) == ['haskel-lang', 'make', 'ruby-lang']


def test_own_components_unaffected_by_subprofile_exclude():
    # ts OWNS nothing (only include + excludes) -> profile_own_components is empty.
    c = cfg('{ configs: [ ts ]  profiles: { ts: [ +languages  ~ruby-lang ] } }')
    assert c.profile_own_components('ts') == []
