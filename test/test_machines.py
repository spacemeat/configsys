'''`machines:` as a composing LAYER (part 6 v1 foundation). A selected `machine:`'s profiles/configs
splice in as a `machine`-role rung that overlays the shared primary/repo profiles by name (so `+self`
and provenance flow) but sits below the local top config.'''

from configsys import layers
from configsys.config import Config, _inject_machine_layer


def _cfg(*specs):
    '''(role, text) low->high, with the machine layer spliced in per the `machine:` setting.'''
    ll = [layers.Layer(f'{r}.hu', r, layers.materialize_string(t)) for r, t in specs]
    return Config(_inject_machine_layer(ll))


REPO = '{ profiles: { tools: [ gimp  inkscape  krita ] } }'
LAPTOP = ('{ machine: laptop  machines: { laptop: { configs: [ tools ] '
          '  profiles: { tools: [ "+tools"  wacom ] } } } }')


def test_machine_profile_overlays_shared_by_name_via_self_track():
    c = _cfg(('repo', REPO), ('user', LAPTOP))
    assert c.selected_machine() == 'laptop' and set(c.machines()) == {'laptop'}
    # the machine's `tools` tracks the SHARED tools (+self -> next-lower = repo) and adds one
    assert set(c.profile_components('tools')) == {'gimp', 'inkscape', 'krita', 'wacom'}
    assert c.profile_relation('tools') == 'tracked'
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


def _rctx(tmp_path, machine=None):
    from configsys.app import Context, build_parser
    argv = ['--home', str(tmp_path), '--os', 'pop']
    if machine:
        argv += ['--machine', machine]
    ctx = Context(build_parser().parse_args(argv + ['inspect']))
    ctx.ensure_user_config()
    return ctx


def test_machines_writer_roundtrip(tmp_path):
    from configsys import plugins
    f = tmp_path / 'u.hu'
    f.write_text('{ // keep\n  scope: user }\n', encoding='utf-8')
    data = {'lap': {'configs': ['a', 'b'], 'profiles': {'x': ['+x', 'c', '~d']}},
            'desk': {'profiles': {'x': ['+y']}}}
    plugins.set_machines(str(f), data)
    assert plugins.read_machines(str(f)) == data
    assert '// keep' in f.read_text() and 'scope: user' in f.read_text()   # comment + sibling survive
    assert '~d' in f.read_text()                                            # terms round-trip


def test_machine_lifecycle_and_scoped_edit(tmp_path):
    from configsys import actions
    ctx = _rctx(tmp_path)
    assert actions.add_machine(ctx, 'laptop')[0] and actions.add_machine(ctx, 'desktop')[0]
    assert actions.add_machine(ctx, 'laptop')[0] is False              # duplicate
    assert set(ctx.config.machines()) == {'laptop', 'desktop'}
    actions.set_machine_active(ctx, 'laptop')
    assert ctx.config.selected_machine() == 'laptop'

    # on-box scoped edit: machine: laptop is active, so the laptop rung is loaded
    changed, label = actions.set_profile_membership(ctx, 'finders', 'bat', 'add',
                                                    machine='laptop')
    assert changed and label == 'machine laptop'
    assert 'bat' in ctx.config.profile_components('finders')           # resolves via the machine layer
    terms = ctx.config.machines()['laptop']['profiles']['finders']
    assert terms[0] == '+finders' and 'bat' in terms                  # tracked into the namespace

    # off-box scoped edit needs --machine (the override loads THAT machine's rung)
    assert actions.set_profile_membership(ctx, 'finders', 'bat', 'add', machine='desktop')[0] is False
    ctx.machine_override = 'desktop'
    ctx.invalidate()
    changed, label = actions.set_profile_membership(ctx, 'finders', 'eza', 'add',   # eza ∉ finders
                                                    machine='desktop')
    assert changed and label == 'machine desktop'
    assert ctx.config.machines()['desktop']['profiles']['finders'][0] == '+finders'
    # laptop's edit is untouched by desktop's
    assert 'bat' in ctx.config.machines()['laptop']['profiles']['finders']

    assert actions.remove_machine(ctx, 'laptop')[0]
    assert 'laptop' not in ctx.config.machines()


def test_machine_inherits_a_shared_primary_profile():
    # the headline want: a shared profile lives at the primary's TOP LEVEL (travels) and a machine
    # derives it. The machine layer sits above primary, below the local top config.
    primary = '{ profiles: { dev: [ gh  git  lazygit ] } }'
    user = ('{ machine: laptop  machines: { laptop: { configs: [ dev ] '
            '  profiles: { dev: [ "+dev"  delta ] } } } }')
    c = _cfg(('repo', '{ }'), ('primary', primary), ('user', user))
    assert set(c.profile_components('dev')) == {'gh', 'git', 'lazygit', 'delta'}   # tracks shared 3 + 1
    assert c.profile_relation('dev') == 'tracked'
    assert [d['role'] for d in c.profile_layer_defs('dev')] == ['primary', 'machine']
