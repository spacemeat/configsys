'''`machines:` as a composing LAYER (part 6 v1 foundation). A selected `machine:`'s profiles/configs
splice in as a `machine`-role rung that overlays the shared primary/repo profiles by name (so `^self`
and provenance flow) but sits below the local top config. See docs/profiles-derive-plan.md.'''

from configsys import layers
from configsys.config import Config, _inject_machine_layer


def _cfg(*specs):
    '''(role, text) low->high, with the machine layer spliced in per the `machine:` setting.'''
    ll = [layers.Layer(f'{r}.hu', r, layers.materialize_string(t)) for r, t in specs]
    return Config(_inject_machine_layer(ll))


REPO = '{ profiles: { tools: [ gimp  inkscape  krita ] } }'
LAPTOP = ('{ machine: laptop  machines: { laptop: { configs: [ tools ] '
          '  profiles: { tools: [ "^tools"  gimp  krita ] } } } }')


def test_machine_profile_overlays_shared_by_name_via_self_derive():
    c = _cfg(('repo', REPO), ('user', LAPTOP))
    assert c.selected_machine() == 'laptop' and set(c.machines()) == {'laptop'}
    # the machine's `tools` derives the SHARED tools (^self -> next-lower = repo) and picks 2 of 3
    assert set(c.profile_components('tools')) == {'gimp', 'krita'}
    assert set(c.profile_menu('tools')) == {'gimp', 'inkscape', 'krita'}
    assert c.profile_new('tools') == {'inkscape'}                 # offered, not installed
    # provenance: the profile now has a repo def AND a machine def
    roles = [d['role'] for d in c.profile_layer_defs('tools')]
    assert roles == ['repo', 'machine']


def test_machine_configs_drives_active_set_local_overrides():
    c = _cfg(('repo', REPO), ('user', LAPTOP))
    assert c.active_profiles == ['tools']                         # from the machine's configs:
    # a LOCAL top-config configs: still wins (the box overrides the machine)
    local = LAPTOP[:-2] + '  configs: [ ] }'                      # add an (empty) local configs:
    c2 = _cfg(('repo', REPO), ('user', local))
    assert c2.active_profiles == []                              # local empty configs: shadows machine


def test_unset_machine_is_a_noop():
    c = _cfg(('repo', REPO), ('user', '{ }'))
    assert c.selected_machine() is None
    assert set(c.profile_components('tools')) == {'gimp', 'inkscape', 'krita'}   # the shared def, whole
    assert all(d['role'] != 'machine' for d in c.profile_layer_defs('tools'))


def test_unknown_machine_selection_does_not_brick():
    c = _cfg(('repo', REPO), ('user', '{ machine: nope }'))
    assert c.selected_machine() == 'nope' and c.machines() == {}
    assert set(c.profile_components('tools')) == {'gimp', 'inkscape', 'krita'}   # no layer -> shared


def test_machine_inherits_a_shared_primary_profile():
    # the headline want: a shared profile lives at the primary's TOP LEVEL (travels) and a machine
    # derives it. The machine layer sits above primary, below the local top config.
    primary = '{ profiles: { dev: [ gh  git  lazygit ] } }'
    user = ('{ machine: laptop  machines: { laptop: { configs: [ dev ] '
            '  profiles: { dev: [ "^dev"  gh  git ] } } } }')
    c = _cfg(('repo', '{ }'), ('primary', primary), ('user', user))
    assert set(c.profile_components('dev')) == {'gh', 'git'}      # machine picks 2 of the shared 3
    assert c.profile_new('dev') == {'lazygit'}                    # the shared profile's 3rd -> offered
    assert [d['role'] for d in c.profile_layer_defs('dev')] == ['primary', 'machine']
