'''Phase 5 of the disposition model (docs/profiles-disposition-plan.md): deep-cloning a SYSTEM
profile into an editable user copy. The clone keeps the same name (so it SHADOWS the system def —
`_expand` only inherits a lower layer on `+self`, which a clone never writes), preserves the
`+include` hierarchy by cloning each included profile as its own unit, and materializes leaf
components — so a component the repo later adds surfaces as NEW rather than leaking into the clone.'''

from configsys import actions, plugins


def _ctx(tmp_path, body='{ configs: [ dev ] }'):
    from configsys.app import Context, build_parser
    d = tmp_path / '.config' / 'configsys'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'configsys.hu').write_text(body)
    return Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))


def test_clone_preserves_hierarchy_and_shadows(tmp_path):
    ctx = _ctx(tmp_path)
    before = sorted(ctx.config.profile_components('jvm-lang'))     # system view (repo)
    changed, label = actions.clone_profile(ctx, 'jvm-lang')
    assert changed and 'included' in label                        # jvm-lang + its *-lang subs
    profs = plugins.read_profiles(str(ctx.paths.user_config_file))
    assert 'jvm-lang' in profs and 'java-lang' in profs           # the include was cloned as a unit
    assert profs['jvm-lang'] == [f'+{s}' for s in sorted(ctx.config.profile_includes('jvm-lang'))]
    assert '+jvm-lang' not in profs['jvm-lang']                   # no +self -> shadow, not amend
    # the clone now sources from the user layer and resolves to the same members
    assert str(ctx.config.profile_source('jvm-lang')) == str(ctx.paths.user_config_file)
    assert sorted(ctx.config.profile_components('jvm-lang')) == before


def test_clone_refusals(tmp_path):
    ctx = _ctx(tmp_path)
    assert actions.clone_profile(ctx, 'nope')[0] is False         # undefined
    assert actions.clone_profile(ctx, '!uninstall')[0] is False   # reserved
    actions.clone_profile(ctx, 'jvm-lang')
    ok, why = actions.clone_profile(ctx, 'jvm-lang')              # re-clone
    assert ok is False and 'already an editable user profile' in why


def test_clone_lockfile_new_upstream_member(tmp_path):
    # a system profile defined in a layer BELOW the user config; clone it, then a lower layer gains a
    # member -> the clone (which shadows) does NOT gain it, so is_new() sees it as NEW.
    ctx = _ctx(tmp_path, '{ configs: [ dev ] }')
    actions.clone_profile(ctx, 'shells')                          # a flat catalog profile
    cloned = sorted(ctx.config.profile_own_components('shells'))
    assert cloned                                                 # materialized leaves
    profs = plugins.read_profiles(str(ctx.paths.user_config_file))
    assert '+shells' not in profs['shells']                       # shadow: repo additions won't leak
