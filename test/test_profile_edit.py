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
    names = [nd[0] for nd in ps.visible_pnodes()]
    assert 'mine' in names and 'base' in names
    ps.lcur = names.index('mine')
    assert ps.cur_node()[3] is True                          # mine is expandable (has an include)
    ps.expand_cur()
    v = ps.visible_pnodes()
    assert any(nd[0] == 'base' and nd[1] == 1 for nd in v)   # base shows indented under mine
    # star `base` -> the catalog filters to base's OWN members
    ps.lcur = next(i for i, nd in enumerate(v) if nd[0] == 'base' and nd[1] == 1)
    ps.toggle_star()
    assert ps.vcatalog() == ['btop']
    ps.toggle_star()                                         # unstar -> full catalog again
    assert len(ps.vcatalog()) == len(ps.catalog)
    # starring `mine` (which only INCLUDES base, no own members) contributes nothing — the star
    # filter is OWN members only, not via-include ones
    ps.lcur = [nd[0] for nd in ps.visible_pnodes()].index('mine')
    ps.toggle_star()
    assert ps.vcatalog() == []                               # 'btop' comes via +base, so it's excluded
