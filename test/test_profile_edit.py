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


# -- self-amend of a lower-layer-only profile ------------------------------

def test_add_to_lower_only_profile_writes_self_then_edit():
    # dev is defined only in repo; the first amend writes +self then the edit — the live amend.
    c = cfg(REPO, '{ }')
    assert plan(c, 'dev', 'ripgrep', 'add') == ['+dev', 'ripgrep']


def test_profile_relation_tracked_shadowed_base():
    assert cfg(REPO).profile_relation('dev') == 'base'                                  # single (repo) def
    assert cfg(REPO, '{ profiles: { dev: [ +dev  x ] } }').profile_relation('dev') == 'tracked'
    assert cfg(REPO, '{ profiles: { dev: [ x  y ] } }').profile_relation('dev') == 'shadowed'


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


def test_profiles_writer_quotes_caret_terms(tmp_path):
    # a `^`-leading term MUST be re-emitted QUOTED — `^` is humon's heredoc sigil, so a bare `^ai`
    # would misparse. Round-trip proves the writer stays humon-safe (the algebra no longer USES `^`).
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
    assert ctx.config.profile_components('demo') == ['btop']
    changed, _msg = actions.remove_profile(ctx, 'demo')
    assert changed
    assert 'demo' not in ctx.config.profile_names()


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


def test_profile_tree_and_browse(tmp_path):
    # v3: flat BROWSE list — `!all` first (the whole catalog), then repo/plugin profiles; the catalog
    # is always scoped to the selected profile's members (no `*` toggle).
    from configsys.tui import menu
    ctx = _rctx(tmp_path)
    ps = menu.ProfileScreen(ctx)
    ps.attr_exc = set()
    names = [nd[0] for nd in ps.visible_pnodes()]
    assert names[0] == '!all'                                  # the browse-everything lens, first
    assert 'finders' in names and 'languages' in names        # repo browse profiles
    assert not any(ps.is_group_header(nd) for nd in ps.visible_pnodes())   # flat, no layer groups
    ps.lcur = 0                                                # !all -> the whole catalog
    assert len(ps.vcatalog()) == len(ps.catalog)
    ps.lcur = names.index('finders')                          # a profile -> its members only
    assert set(ps.vcatalog()) == set(ctx.config.profile_components('finders'))


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


def test_add_profile_allows_same_name_as_system(tmp_path):
    # a new user profile may reuse a SYSTEM profile's name (it shadows the browse original — the
    # disposition model's clone); only a second EDITABLE profile of that name is refused.
    from configsys import actions
    ctx = _rctx(tmp_path)
    assert 'ai-tools' in ctx.config.profile_names()               # a repo (system) profile
    ok, _lbl = actions.add_profile(ctx, 'ai-tools')               # same name -> allowed now
    assert ok
    assert str(ctx.config.profile_source('ai-tools')) == str(ctx.paths.user_config_file)
    ok2, why = actions.add_profile(ctx, 'ai-tools')               # now an editable one exists -> refused
    assert ok2 is False and 'already exists' in why


def test_profile_new_count_badge(tmp_path):
    # ⁺N badge: NEW (undispositioned, not in a user profile) members of a profile; drops as you triage.
    from configsys import actions
    from configsys.tui import menu
    ctx = _rctx(tmp_path)
    ps = menu.ProfileScreen(ctx)
    ceil = ps.group_ceiling('repo')
    before = ps.profile_new_count('shells', ceil)
    assert before == len(ps.members('shells', ceil))         # a fresh home: every member is NEW
    assert ps.group_new_count('repo')[0] > 0                 # (NEW, interesting); the repo group has NEW work

    one = sorted(ps.members('shells', ceil))[0]
    actions.set_disposition(ctx, one, 'interesting')         # triage one -> interesting
    ps = menu.ProfileScreen(ctx)                             # reload -> caches rebuild
    assert ps.profile_new_count('shells', ceil) == before - 1
    assert ps.profile_interesting_count('shells', ceil) == 1   # ☆N tracks bookmarks


def test_parts_component_installed_iff_all_parts(tmp_path):
    # a `via: parts` aggregator (docker) has no unit of its own -> it reads installed only when ALL
    # its parts are installed (batch set or probe).
    from configsys.tui import menu
    ctx = _rctx(tmp_path)
    ps = menu.ProfileScreen(ctx)
    ps.show_install = 1
    assert ps._parts('docker') == ['docker-engine', 'docker-service']
    ps._overlay = (frozenset(), {}, frozenset()); ps._probe_installed = {}
    assert ps.is_installed('docker') is False                 # none installed
    ps._overlay = (frozenset({'docker-engine'}), {}, frozenset())
    assert ps.is_installed('docker') is False                 # only one part
    ps._probe_installed = {'docker-service': True}            # the other part via probe
    assert ps.is_installed('docker') is True                  # all parts -> installed


def test_install_probe_underlines_nonenumerable(tmp_path):
    # the install-underline probe: a tarball/script component (no batch installed_index) that's on
    # disk is detected by an individual get_version probe, so it underlines like a native package.
    import time
    from configsys.drivers import get_driver
    from configsys.tui import menu
    ctx = _rctx(tmp_path)
    units, _ = ctx.routes.resolve_resilient(['ollama'])          # ollama installs via tarball
    u = next(v for v in units.values() if v.name == 'ollama')
    assert u.driver == 'tarball'
    drv = get_driver(u.driver, ctx.runner, ctx.paths)
    d = drv._install_dir(u); d.mkdir(parents=True, exist_ok=True)
    drv._marker(u).write_text('9.9.9')                           # simulate an install

    ps = menu.ProfileScreen(ctx)
    ps.show_install = 1
    ps._overlay = (frozenset(), {}, frozenset())                 # batch overlay ran; ollama not in it
    ps.ensure_probes(['ollama', 'fzf'])                          # fzf is native -> enumerable -> skipped
    for _ in range(50):
        if not ps.probe_busy():
            break
        time.sleep(0.1)
    assert ps._probe_installed.get('ollama') is True             # probe found it -> will underline
    assert 'fzf' not in ps._probe_installed                      # enumerable driver, not probed


def test_profile_multiselect_batch_targets(tmp_path):
    # `space` builds a multi-select set that A/I/S/X act on as a batch (spanning the current scope);
    # with no selection the actions target just the cursor component.
    from configsys import actions
    from configsys.tui import menu
    ctx = _rctx(tmp_path)
    actions.add_profile(ctx, 'mine')
    actions.set_profile_membership(ctx, 'mine', 'btop', 'add')
    actions.set_profile_membership(ctx, 'mine', 'htop', 'add')

    ps = menu.ProfileScreen(ctx)
    ps.attr_exc = set()
    ps.lcur = 0                                                  # !all -> the full catalog is in view
    ps.rcur = 0
    ps.focus = 'right'
    cursor = ps.vcatalog()[0]
    assert ps.action_targets() == [cursor]                       # right pane, no selection -> the cursor
    # browse pane focused, no selection -> the whole selected profile's members
    ps.focus = 'left'
    ps.lcur = [nd[0] for nd in ps.visible_pnodes()].index('finders')
    assert set(ps.action_targets()) == set(ctx.config.profile_components('finders'))
    ps.selected_comps = {'btop', 'htop'}                         # `space` set (spans, either pane)
    assert ps.action_targets() == ['btop', 'htop']               # selection -> the whole set (sorted)
    # a disposition batch clears the set and applies to all
    for c in ps.action_targets():
        actions.set_disposition(ctx, c, 'interesting')
    assert ctx.config.disposition('btop') == 'interesting'
    assert ctx.config.disposition('htop') == 'interesting'


def test_profile_pane_is_flat_browse_only(tmp_path):
    # v3: the left pane is a FLAT browse list of repo/plugin profiles — no layer group headers, and
    # authored user-layer profiles are NOT shown (irrelevant in the matrix model).
    from configsys import actions
    from configsys.tui import menu
    ctx = _rctx(tmp_path)
    actions.add_profile(ctx, 'zmine')                          # a user-layer profile
    ps = menu.ProfileScreen(ctx)
    v = ps.visible_pnodes()
    assert not any(ps.is_group_header(nd) for nd in v)         # no group headers (flat)
    names = {nd[0] for nd in v}
    assert 'finders' in names                                  # repo browse profiles present
    assert 'zmine' not in names                                # user-authored profile hidden
    assert '!all' in names and '!uninstall' in names          # the two keyword browse lenses show


def test_where_profile_report(tmp_path):
    from configsys import actions
    from configsys.app import where_profile_report
    ctx = _rctx(tmp_path)
    assert where_profile_report(ctx, 'no-such-profile') is None
    # amend a repo profile from the top config, then the report names the relation + the layers
    actions.set_profile_membership(ctx, 'finders', 'bat', 'add')
    txt = '\n'.join(where_profile_report(ctx, 'finders'))
    assert 'relation: tracked' in txt and 'config.hu (repo)' in txt and '[user]' in txt
    assert 'members' in txt


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
