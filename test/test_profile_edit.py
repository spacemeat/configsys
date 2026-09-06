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


# -- BALLOT (derived-profile decline / clear) -----------------------------

BALLOT = '{ profiles: { ai: [ claude-code  ollama  aider ]  m: [ "^ai"  claude-code ] } }'


def test_decline_a_new_menu_item_writes_negation():
    # ollama/aider are offered (NEW) by ^ai but not picked; declining writes ~aider
    c = cfg(BALLOT)
    assert plan(c, 'm', 'aider', 'decline', target='config.hu') == ['^ai', 'claude-code', '~aider']


def test_decline_a_pick_drops_the_pick_and_negates():
    c = cfg(BALLOT)
    assert plan(c, 'm', 'claude-code', 'decline', target='config.hu') == ['^ai', '~claude-code']


def test_clear_a_pick_returns_to_offered():
    c = cfg(BALLOT)
    assert plan(c, 'm', 'claude-code', 'clear', target='config.hu') == ['^ai']


def test_clear_a_decline_returns_to_offered():
    c = cfg('{ profiles: { ai: [ claude-code  ollama ]  m: [ "^ai"  ~ollama ] } }')
    assert plan(c, 'm', 'ollama', 'clear', target='config.hu') == ['^ai']


def test_decline_already_declined_is_a_noop():
    c = cfg('{ profiles: { ai: [ claude-code  ollama ]  m: [ "^ai"  ~ollama ] } }')
    assert plan(c, 'm', 'ollama', 'decline', target='config.hu') is None


def test_clear_when_nothing_owned_is_a_noop():
    c = cfg(BALLOT)
    assert plan(c, 'm', 'ollama', 'clear', target='config.hu') is None       # ollama is unballoted


# -- PIN vs TRACK (synth of a first amend of a lower-layer-only profile) ----

def test_synth_track_amends_via_self():
    # dev is defined only in repo; TRACK (default) writes +self then the edit — the live amend.
    c = cfg(REPO, '{ }')
    assert plan(c, 'dev', 'ripgrep', 'add') == ['+dev', 'ripgrep']              # track = current behavior


def test_synth_pin_snapshots_members_and_adds():
    # PIN writes ^self + the current members as picks, then the added comp — upstream growth becomes NEW.
    c = cfg(REPO, '{ }')
    got = c.plan_membership_edit('dev', 'ripgrep', 'add', 'user.hu', synth='pin')
    assert got[0] == '^dev' and set(got[1:]) == {'btop', 'fzf', 'ripgrep'}


def test_synth_pin_remove_declines_the_component():
    # PIN remove snapshots members minus the comp AND declines it (quiet, not re-offered as NEW).
    c = cfg(REPO, '{ }')
    got = c.plan_membership_edit('dev', 'fzf', 'remove', 'user.hu', synth='pin')
    assert got[0] == '^dev' and 'btop' in got and '~fzf' in got and 'fzf' not in got[1:]


def test_synth_ignored_once_in_target():
    # synth only matters at the FIRST amend; once the profile is in the target layer, pin == track.
    c = cfg(REPO, '{ profiles: { dev: [ +dev ] } }')
    assert (plan(c, 'dev', 'ripgrep', 'add')
            == c.plan_membership_edit('dev', 'ripgrep', 'add', 'user.hu', synth='pin')
            == ['+dev', 'ripgrep'])


def test_profile_amends_lower_predicate():
    c = cfg(REPO, '{ profiles: { mine: [ btop ] } }')
    assert c.profile_amends_lower('dev', 'user.hu') is True        # dev only in repo -> first amend
    assert c.profile_amends_lower('mine', 'user.hu') is False      # already in the target layer
    assert c.profile_amends_lower('nope', 'user.hu') is False      # undefined -> nothing to amend


def test_profile_relation_pinned_tracked_shadowed_base():
    assert cfg(REPO).profile_relation('dev') == 'base'                                  # single (repo) def
    assert cfg(REPO, '{ profiles: { dev: [ +dev  x ] } }').profile_relation('dev') == 'tracked'
    assert cfg(REPO, '{ profiles: { dev: [ "^dev"  btop ] } }').profile_relation('dev') == 'pinned'
    assert cfg(REPO, '{ profiles: { dev: [ x  y ] } }').profile_relation('dev') == 'shadowed'


def test_ballot_roundtrips_through_membership_and_menu():
    # pick an offered item, then decline it, then clear it — membership/new track each step.
    text = '{ profiles: { ai: [ a  b  cc ]  m: [ "^ai"  a ] } }'
    def eff(terms):
        c = Config([layers.Layer('config.hu', 'repo',
                                 layers.materialize_string(text.replace('"^ai"  a', ' '.join(terms))))])
        return set(c.profile_components('m')), c.profile_new('m'), c.profile_removed('m')
    m, new, rem = eff(['"^ai"', 'a', 'b'])                     # pick b
    assert 'b' in m and 'b' not in new
    m, new, rem = eff(['"^ai"', 'a', '~b'])                    # decline b
    assert 'b' not in m and 'b' not in new and 'b' in rem
    m, new, rem = eff(['"^ai"', 'a'])                          # clear b -> offered again
    assert 'b' not in m and 'b' in new


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


def test_profiles_writer_quotes_derive_terms(tmp_path):
    # a `^derive` term MUST be re-emitted QUOTED — `^` is humon's heredoc sigil, so a bare `^ai`
    # would misparse. Round-trip proves the written file still reads back the same term list.
    f = tmp_path / 'u.hu'
    f.write_text('{ profiles: {} }\n', encoding='utf-8')
    plugins.set_profiles(str(f), {'m': ['^ai', 'claude-code', '~aider']})
    assert '"^ai"' in f.read_text()                          # quoted in the file
    assert plugins.read_profiles(str(f)) == {'m': ['^ai', 'claude-code', '~aider']}


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
    ps.cycle_star()                                          # off -> star base (filter + always show-removed)
    assert ps.show_removed is True and ps.vcatalog() == ['btop']   # base pruned nothing -> just its member
    ps.cycle_star()                                          # -> off: full catalog again
    assert not ps.starred and not ps.show_removed and len(ps.vcatalog()) == len(ps.catalog)
    # starring `mine` (which +includes base) now stars the whole inheritance chain, so base's OWN
    # members come along — the clone-and-prune view (see the base's members + a derived profile's ~drops)
    ps.lcur = [nd[0] for nd in ps.visible_pnodes()].index('mine')
    ps.cycle_star()
    assert ps.starred == {'mine', 'base'}                    # * stars the profile AND its includes
    assert ps.show_removed is True                           # filter always reveals removals (no members-only state)
    assert ps.vcatalog() == ['btop']                         # base's own member is now visible
    ps.cycle_star()                                          # -> off: the whole chain clears
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


def test_profile_ballot_view_and_edits(tmp_path):
    # A derived profile is a ballot: the ProfileScreen surfaces menu/new/subtree helpers, and the
    # decline/clear writers cycle a menu item NEW -> pick -> decline -> NEW through the real config.
    from configsys import actions, plugins
    from configsys.tui import menu
    ctx = _rctx(tmp_path)
    actions.add_profile(ctx, 'ai')
    for comp in ('claude-code', 'ollama', 'aider'):
        actions.set_profile_membership(ctx, 'ai', comp, 'add')
    uf = str(ctx.paths.user_config_file)
    profs = plugins.read_profiles(uf)
    profs['m'] = ['^ai', 'claude-code']                      # derive from ai; pick claude-code
    plugins.set_profiles(uf, profs)
    ctx.invalidate()

    ps = menu.ProfileScreen(ctx)
    assert ps.is_derived('m') and not ps.is_derived('ai')
    assert ps.menu('m') == {'claude-code', 'ollama', 'aider'}
    assert ps.members('m') == {'claude-code'}
    assert ps.new_members('m') == {'ollama', 'aider'}
    assert ps.subtree_new('m') == {'ollama', 'aider'} and ps.subtree_new('ai') == set()

    # pick an offered item, then decline it, then clear it back to offered
    actions.set_profile_membership(ctx, 'm', 'ollama', 'add')
    assert 'ollama' in menu.ProfileScreen(ctx).members('m')
    actions.set_profile_membership(ctx, 'm', 'ollama', 'decline')
    ps2 = menu.ProfileScreen(ctx)
    assert 'ollama' not in ps2.members('m') and 'ollama' in ps2.removed_members('m')
    actions.set_profile_membership(ctx, 'm', 'ollama', 'clear')
    ps3 = menu.ProfileScreen(ctx)
    assert 'ollama' in ps3.new_members('m') and 'ollama' not in ps3.removed_members('m')


def test_pin_edit_over_a_repo_profile_roundtrip(tmp_path):
    # Editing a repo-only profile with synth='pin' writes a ^self derivation seeded with the current
    # members, so effective membership is unchanged today; the repo def becomes an offered MENU.
    from configsys import actions, plugins
    ctx = _rctx(tmp_path)
    before = set(ctx.config.profile_components('finders'))         # repo catalog profile
    assert 'ripgrep' not in before or before                      # sanity: it has members
    changed, _lbl = actions.set_profile_membership(ctx, 'finders', 'bat', 'add', synth='pin')
    assert changed
    terms = plugins.read_profiles(str(ctx.paths.user_config_file))['finders']
    assert terms[0] == '^finders' and 'bat' in terms             # pinned + the new pick
    assert ctx.config.profile_relation('finders') == 'pinned'
    assert set(ctx.config.profile_components('finders')) == before | {'bat'}   # same today + the add
    assert before <= ctx.config.profile_menu('finders')          # repo members are now the menu


def test_profile_edit_mode_setting(tmp_path):
    from configsys import actions
    ctx = _rctx(tmp_path)
    assert ctx.config.profile_edit_mode() == 'ask'                # default
    actions.set_config_setting(ctx, 'profile-edit-mode', ['pin'])
    assert ctx.config.profile_edit_mode() == 'pin'
    actions.set_config_setting(ctx, 'profile-edit-mode', ['bogus'])
    assert ctx.config.profile_edit_mode() == 'ask'               # unknown -> default


def test_where_profile_report(tmp_path):
    from configsys import actions, plugins
    from configsys.app import where_profile_report
    ctx = _rctx(tmp_path)
    assert where_profile_report(ctx, 'no-such-profile') is None
    # pin a repo profile, then the report names the relation + the layers
    actions.set_profile_membership(ctx, 'finders', 'bat', 'add', synth='pin')
    txt = '\n'.join(where_profile_report(ctx, 'finders'))
    assert 'relation: pinned' in txt and 'config.hu (repo)' in txt and '[user]' in txt
    assert 'menu' in txt and 'new' in txt


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


def test_overlay_paints_installed_fast_then_folds_orphans_async(tmp_path, monkeypatch):
    # `O` must never block: the installed underlines paint immediately from the seed, and the orphan
    # scan (the ~1s part) runs on a daemon thread and folds in on a later redraw. Stub the two orphans
    # entry points so the split + fold is deterministic (real scans spawn apt/flatpak).
    import threading
    from configsys.tui import menu
    from configsys import orphans as O
    ctx = _rctx(tmp_path)
    monkeypatch.setattr(O, 'installed_overlay', lambda ctx, caches: {'htop'})   # instant fast path
    gate = threading.Event()

    def fake_full(ctx, units, caches=None):
        gate.wait(5)                                    # let the test control when the scan "finishes"
        return {'htop', 'btop'}, {'ncdu': object()}, (caches if caches is not None else {})
    monkeypatch.setattr(O, 'install_overlay', fake_full)

    ps = menu.ProfileScreen(ctx)
    ps.show_install = 1
    inst, orph, _uq = ps.overlay()                      # first paint
    assert inst == {'htop'} and orph == {}             # underlines now, orphans not yet
    assert ps.overlay_busy()                            # background scan in flight
    gate.set()
    ps._ov_thread.join(timeout=5)
    inst2, orph2, _uq2 = ps.overlay()                   # fold the async result
    assert inst2 == {'htop', 'btop'} and set(orph2) == {'ncdu'}
    assert not ps.overlay_busy()


def test_overlay_off_is_empty_and_not_busy(tmp_path):
    from configsys.tui import menu
    ps = menu.ProfileScreen(_rctx(tmp_path))
    assert ps.show_install == 1                          # default ON
    ps.show_install = 0                                  # turn it off
    assert ps.overlay() == (frozenset(), {}, frozenset())
    assert not ps.overlay_busy()
