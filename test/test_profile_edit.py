'''Profile term-algebra WRITER (Config.plan_membership_edit) + the surgical profile/configs file
writers (plugins.read/set_profiles, read/set_configs). This is the F3 foundation for the TUI's
Profiles screen and the `configsys profile` CLI — the subtle piece, so it gets a full matrix.

The planner is PURE: given the merged config + an edit-target layer, it returns the new raw term
list to write into that layer's profile (or None for a no-op), honoring +dev / +other / ~.'''

from configsys import layers, plugins
from configsys.config import Config


def cfg(repo_text, user_text=None):
    ls = [layers.Layer('config.hu', 'repo', layers.materialize_string(repo_text))]
    if user_text is not None:
        ls.append(layers.Layer('user.hu', 'user', layers.materialize_string(user_text)))
    return Config(ls)


REPO = '{ profiles: { dev: [ btop  fzf ]  base: [ git  curl ] } }'


def plan(c, profile, comp, action, target='user.hu'):
    return c.plan_membership_edit(profile, comp, action, target)


# -- ADD ------------------------------------------------------------------

def test_add_to_own_top_layer_appends_bare():
    c = cfg(REPO, '{ profiles: { dev: [ btop ] } }')
    assert plan(c, 'dev', 'ripgrep', 'add') == ['btop', 'ripgrep']


def test_add_to_lower_only_profile_amends_with_self():
    # dev is defined only in repo; the user layer must inherit (+dev) then add
    c = cfg(REPO, '{ }')
    assert plan(c, 'dev', 'ripgrep', 'add') == ['+dev', 'ripgrep']


def test_add_when_already_member_is_a_noop():
    c = cfg(REPO, '{ profiles: { dev: [ +dev ] } }')     # dev == repo's [btop, fzf]
    assert plan(c, 'dev', 'btop', 'add') is None


def test_add_undoes_a_suppressing_negation():
    c = cfg(REPO, '{ profiles: { dev: [ +dev  ~btop ] } }')   # btop currently removed
    assert plan(c, 'dev', 'btop', 'add') == ['+dev']          # drop the ~btop


def test_add_brand_new_profile():
    c = cfg(REPO, '{ }')
    assert plan(c, 'mine', 'neovim', 'add') == ['neovim']      # no +dev (nothing below)


# -- REMOVE ---------------------------------------------------------------

def test_remove_bare_own_term_only_source():
    c = cfg('{ profiles: { dev: [ ] } }', '{ profiles: { dev: [ btop  ripgrep ] } }')
    assert plan(c, 'dev', 'ripgrep', 'remove') == ['btop']


def test_remove_member_from_lower_layer_negates_via_self():
    # fzf comes only from repo's dev; the user layer amends with +dev then ~fzf
    c = cfg(REPO, '{ }')
    assert plan(c, 'dev', 'fzf', 'remove') == ['+dev', '~fzf']


def test_remove_member_brought_by_an_include_negates():
    c = cfg(REPO, '{ profiles: { dev: [ +base  btop ] } }')     # dev = git,curl,btop
    assert plan(c, 'dev', 'git', 'remove') == ['+base', 'btop', '~git']


def test_remove_bare_term_that_is_also_present_below():
    # user redundantly re-adds btop that repo already has; a real remove must drop the bare
    # term AND negate the inherited one
    c = cfg(REPO, '{ profiles: { dev: [ +dev  btop ] } }')
    assert plan(c, 'dev', 'btop', 'remove') == ['+dev', '~btop']


def test_remove_when_absent_is_a_noop():
    c = cfg(REPO, '{ profiles: { dev: [ btop ] } }')
    assert plan(c, 'dev', 'nope', 'remove') is None


# -- round-trip: the planned terms actually produce the intended membership -------

def _roundtrip(repo_text, user_terms, profile, comp, action):
    '''Apply a planned edit to an in-memory user layer and return the new effective membership.'''
    user = {'profiles': {profile: user_terms}} if user_terms is not None else {'profiles': {}}
    c = Config([layers.Layer('config.hu', 'repo', layers.materialize_string(repo_text)),
                layers.Layer('user.hu', 'user', user)])
    new = c.plan_membership_edit(profile, comp, action, 'user.hu')
    if new is not None:
        user['profiles'][profile] = new
    c2 = Config([layers.Layer('config.hu', 'repo', layers.materialize_string(repo_text)),
                 layers.Layer('user.hu', 'user', user)])
    return c2.profile_components(profile)


def test_roundtrip_add_and_remove_yield_intended_membership():
    assert 'ripgrep' in _roundtrip(REPO, None, 'dev', 'ripgrep', 'add')          # +dev add
    assert 'fzf' not in _roundtrip(REPO, None, 'dev', 'fzf', 'remove')           # +dev ~
    assert 'git' not in _roundtrip(REPO, ['+base', 'btop'], 'dev', 'git', 'remove')
    assert 'btop' not in _roundtrip(REPO, ['+dev', 'btop'], 'dev', 'btop', 'remove')


# -- file writers: read/emit/set round-trip + comment preservation ---------

def test_profiles_writer_roundtrip_and_preserves_outside_comments(tmp_path):
    f = tmp_path / 'u.hu'
    f.write_text('{\n    // keep me\n    configs: [ dev ]\n'
                 '    profiles: { dev: [ btop  fzf ] }\n}\n', encoding='utf-8')
    profs = plugins.read_profiles(str(f))
    assert profs == {'dev': ['btop', 'fzf']}
    profs['dev'] = ['btop', 'fzf', 'ripgrep']
    plugins.set_profiles(str(f), profs)
    assert plugins.read_profiles(str(f)) == {'dev': ['btop', 'fzf', 'ripgrep']}
    assert '// keep me' in f.read_text()          # comment outside the edited node survives
    assert 'configs: [ dev ]' in f.read_text()    # sibling section untouched


def test_configs_writer_roundtrip(tmp_path):
    f = tmp_path / 'u.hu'
    f.write_text('{ configs: [ dev ] }\n', encoding='utf-8')
    assert plugins.read_configs(str(f)) == ['dev']
    plugins.set_configs(str(f), ['dev', 'games'])
    assert plugins.read_configs(str(f)) == ['dev', 'games']
    plugins.set_configs(str(f), [])               # empty -> node removed
    assert plugins.read_configs(str(f)) == []


def test_profile_membership_provenance():
    # dev includes base, adds neovim, removes gdb — the markers the Profiles screen shows.
    c = cfg('{ profiles: { base: [ btop  ripgrep  gdb ]  dev: [ +base  neovim  ~gdb ] } }')
    assert set(c.profile_components('dev')) == {'btop', 'ripgrep', 'neovim'}   # gdb removed
    own = set(c.profile_own_components('dev'))
    assert 'neovim' in own and 'btop' not in own          # neovim direct (●); btop via +base (↳)
    assert c.profile_removed('dev') == {'gdb'}             # ~gdb (~)


# -- add / remove whole profiles (actions over a real Context) ------------

def _rctx(tmp_path):
    from configsys.app import Context, build_parser
    ctx = Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))
    ctx.ensure_user_config()
    return ctx


def test_add_and_remove_profile_roundtrip(tmp_path):
    from configsys import actions
    ctx = _rctx(tmp_path)
    changed, _lbl = actions.add_profile(ctx, 'demo')
    assert changed and 'demo' in ctx.config.profile_names()
    assert ctx.config.profile_components('demo') == []          # a fresh, empty profile
    assert actions.add_profile(ctx, 'demo')[0] is False          # duplicate
    assert actions.add_profile(ctx, 'all')[0] is False           # reserved
    assert actions.add_profile(ctx, '   ')[0] is False           # empty
    actions.set_profile_membership(ctx, 'demo', 'btop', 'add')
    actions.set_profile_active(ctx, 'demo', True)
    assert 'demo' in set(ctx.config.active_profiles)
    changed, _msg = actions.remove_profile(ctx, 'demo')
    assert changed
    assert 'demo' not in ctx.config.profile_names()
    assert 'demo' not in set(ctx.config.active_profiles)         # deactivated on the way out


def test_remove_profile_refuses_a_non_editable_layer(tmp_path):
    from configsys import actions
    ctx = _rctx(tmp_path)
    repo_defined = ctx.config.profile_names()[0]                 # all come from the repo at fresh install
    changed, msg = actions.remove_profile(ctx, repo_defined)
    assert changed is False and 'not editable' in msg


def test_membership_edit_never_writes_the_repo_baseline(tmp_path):
    '''Regression: adding to a profile defined ONLY in the repo (e.g. `dev`) must NOT mutate the
    shipped config.hu — it amends from the editable layer (top config / primary) via +self. Bug:
    _profile_target returned profile_source() = the repo file, so TUI edits wrote into the repo.'''
    import pathlib

    from configsys import actions
    ctx = _rctx(tmp_path)
    repo_defined = 'dev-tools'
    assert repo_defined in ctx.config.profile_names()               # ships in the repo config.hu
    repo_file = pathlib.Path(ctx.paths.config_file)
    before = repo_file.read_text()

    tf, _label = actions._profile_target(ctx, repo_defined)
    assert str(tf) != str(repo_file)                                # never the repo
    assert str(tf) == str(ctx.paths.user_config_file)               # -> this machine's top config

    comp = 'hyperfine'                                             # a real component NOT in dev
    assert comp not in ctx.config.profile_components(repo_defined)
    changed, _lbl = actions.set_profile_membership(ctx, repo_defined, comp, 'add')
    assert changed
    assert comp in ctx.config.profile_components(repo_defined)      # effective (via +self amend)
    assert repo_file.read_text() == before                         # the repo template is untouched
    # the write landed in the top config as a self-amend, not a shadowing full copy
    assert plugins.read_profiles(str(ctx.paths.user_config_file))[repo_defined][0] == '+' + repo_defined


def test_remove_last_profile_keeps_the_file_and_comments(tmp_path):
    '''Regression: set_profiles({}) -> remove_sections used to take the whole file with the profiles
    node's bound leading comments, wiping the config to `{}`.'''
    import pathlib

    from configsys import actions, layers
    ctx = _rctx(tmp_path)
    f = pathlib.Path(ctx.paths.user_config_file)
    actions.add_profile(ctx, 'solo')
    actions.remove_profile(ctx, 'solo')
    txt = f.read_text()
    assert 'Override component routes' in txt                    # template comments survived
    assert isinstance(layers.materialize_string(txt), dict)      # and it still parses


def test_include_and_uninclude_profile(tmp_path):
    from configsys import actions
    ctx = _rctx(tmp_path)
    actions.add_profile(ctx, 'a')
    actions.add_profile(ctx, 'b')
    actions.set_profile_membership(ctx, 'b', 'btop', 'add')
    changed, _ = actions.set_profile_include(ctx, 'a', 'b', True)      # a includes b -> a gets btop
    assert changed
    assert 'btop' in ctx.config.profile_components('a')
    assert ctx.config.profile_includes('a') == {'b'}
    assert actions.set_profile_include(ctx, 'a', 'a', True)[0] is False        # no self-include
    assert actions.set_profile_include(ctx, 'a', 'nope', True)[0] is False     # unknown profile
    changed, _ = actions.set_profile_include(ctx, 'a', 'b', False)     # drop the include
    assert changed and 'btop' not in ctx.config.profile_components('a')
    assert ctx.config.profile_includes('a') == set()


def test_profile_tree_and_star_filter(tmp_path):
    from configsys import actions
    from configsys.tui import menu
    ctx = _rctx(tmp_path)
    actions.add_profile(ctx, 'base')
    actions.set_profile_membership(ctx, 'base', 'btop', 'add')
    actions.add_profile(ctx, 'mine')
    actions.set_profile_include(ctx, 'mine', 'base', True)   # mine includes base

    ps = menu.ProfileScreen(ctx)
    ps.attr_exc = set()                                      # isolate star filtering from the attrs
    names = [nd[0] for nd in ps.visible_pnodes()]            # filter's default `-dotfiles` hide
    assert 'mine' in names and 'base' in names
    ps.lcur = names.index('mine')
    assert ps.cur_node()[3] is True                          # mine is expandable (has an include)
    ps.expand_cur()
    v = ps.visible_pnodes()
    assert any(nd[0] == 'base' and nd[1] == 1 for nd in v)   # base shows indented under mine
    # star `base` -> the catalog filters to base's OWN members
    ps.lcur = next(i for i, nd in enumerate(v) if nd[0] == 'base' and nd[1] == 1)
    ps.cycle_star()                                          # off -> star base
    assert ps.vcatalog() == ['btop']
    ps.cycle_star()                                          # star -> star + show-removed (base pruned nothing)
    assert ps.show_removed is True and ps.vcatalog() == ['btop']
    ps.cycle_star()                                          # -> off: full catalog again
    assert not ps.starred and len(ps.vcatalog()) == len(ps.catalog)
    # starring `mine` (which +includes base) now stars the whole inheritance chain, so base's OWN
    # members come along — the clone-and-prune view (see the base's members + a derived profile's ~drops)
    ps.lcur = [nd[0] for nd in ps.visible_pnodes()].index('mine')
    ps.cycle_star()
    assert ps.starred == {'mine', 'base'}                    # * stars the profile AND its includes
    assert ps.vcatalog() == ['btop']                         # base's own member is now visible
    ps.cycle_star(); ps.cycle_star()                         # +show-removed, then off -> the whole chain clears
    assert ps.starred == set() and len(ps.vcatalog()) == len(ps.catalog)


def test_find_next_steps_through_siblings():
    # `/` scans from JUST AFTER the cursor, so repeated finds step through equally-scoring siblings
    # (and wrap), while a clearly-better match still wins.
    from configsys.tui.menu import _find_next
    labels = ['alpha', 'gcc-10', 'gcc-11', 'gcc-12', 'zebra']
    assert _find_next(labels, 'gcc', 0) == 1          # alpha -> gcc-10
    assert _find_next(labels, 'gcc', 1) == 2          # gcc-10 -> gcc-11 (the NEXT one)
    assert _find_next(labels, 'gcc', 3) == 1          # gcc-12 -> wraps back to gcc-10
    assert _find_next(labels, 'nope', 0) is None      # nothing matches
    assert _find_next(['xgcc', 'gcc'], 'gcc', 1) == 1  # a boundary/exact match still beats a weaker one


def test_profile_active_direct_vs_indirect(tmp_path):
    # `configs:` profiles are DIRECTLY active (● in the pane); profiles reached via +include from an
    # active one are INDIRECTLY active (◐); the rest inactive (○).
    from configsys import actions
    from configsys.tui import menu
    ctx = _rctx(tmp_path)
    actions.add_profile(ctx, 'leaf')
    actions.set_profile_membership(ctx, 'leaf', 'btop', 'add')
    actions.add_profile(ctx, 'sub')
    actions.set_profile_include(ctx, 'sub', 'leaf', True)
    actions.add_profile(ctx, 'top')
    actions.set_profile_include(ctx, 'top', 'sub', True)
    actions.set_profile_active(ctx, 'top', True)                # only `top` is in configs

    ps = menu.ProfileScreen(ctx)
    assert ps.active == {'top'}                                 # ● directly active
    assert ps.active_indirect == {'sub', 'leaf'}               # ◐ pulled in transitively via +include


def test_profile_star_filter_show_removed(tmp_path):
    # The clone-and-prune view: star a profile, then `~` also reveals the components it dropped via
    # `~term` (marked `~`), so you can see what you pruned — not just what survived.
    from configsys import actions
    from configsys.tui import menu
    ctx = _rctx(tmp_path)
    actions.add_profile(ctx, 'base')
    actions.set_profile_membership(ctx, 'base', 'htop', 'add')
    actions.add_profile(ctx, 'mine')
    actions.set_profile_membership(ctx, 'mine', 'btop', 'add')      # an OWN member
    actions.set_profile_include(ctx, 'mine', 'base', True)          # +base brings htop
    actions.set_profile_membership(ctx, 'mine', 'htop', 'remove')   # prune it -> ~htop
    assert ctx.config.profile_removed('mine') == {'htop'}

    ps = menu.ProfileScreen(ctx)
    ps.attr_exc = set()                                            # isolate from the attrs filter
    # drive the FILTER directly (the `*` cycle is exercised in test_profile_tree_and_star_filter)
    ps.starred = {'mine', 'base'}                                 # the include closure
    # plain star = SURVIVORS: htop is hidden even though base owns it, because mine pruned it (~htop)
    assert ps.vcatalog() == ['btop']
    ps.show_removed = True                                        # reveal what mine pruned via ~htop
    assert ps.vcatalog() == ['btop', 'htop']                     # the pruned htop is shown again
    assert 'htop' in ps._starred_removed()                       # ...and marked as a removal (~)


def test_subprofile_membership_toggle_roundtrip(tmp_path):
    # The Profiles tree's `~` membership toggle: exclude a subprofile from a top-level profile, then
    # re-include it — driven through the same actions wrapper the TUI calls.
    from configsys import actions
    ctx = _rctx(tmp_path)                                         # repo config.hu is the base layer
    actions.add_profile(ctx, 'ts')
    actions.set_profile_include(ctx, 'ts', 'languages', True)     # ts: [ +languages ]
    assert 'ruby-lang' in ctx.config.active_subprofiles('ts')
    assert 'ruby' in ctx.config.profile_components('ts')

    changed, _ = actions.set_subprofile_membership(ctx, 'ts', 'ruby-lang', False)   # exclude
    assert changed
    assert 'ruby-lang' not in ctx.config.active_subprofiles('ts')
    assert 'ruby-lang' in ctx.config.profile_excludes('ts')      # attribution: ts owns the ~
    assert 'ruby' not in ctx.config.profile_components('ts')     # its members are gone

    changed, _ = actions.set_subprofile_membership(ctx, 'ts', 'ruby-lang', True)    # re-include
    assert changed
    assert 'ruby-lang' in ctx.config.active_subprofiles('ts')
    assert 'ruby-lang' not in ctx.config.profile_excludes('ts')  # the ~ term is gone again

    assert actions.set_subprofile_membership(ctx, 'ts', 'ruby-lang', True)[0] is False   # no-op
    assert actions.set_subprofile_membership(ctx, 'ts', 'ts', False)[0] is False         # self refused
    assert actions.set_subprofile_membership(ctx, 'ts', 'nope-lang', False)[0] is False  # unknown
