'''Profile BROWSE-lens reads + the TUI Profiles screen / picks. Profiles are read-only browse lenses
now (repo/plugins); the term algebra (+include / ~remove / +self) still resolves them for the lens,
which is what these exercise, alongside picks/dispositions and the ProfileScreen helpers.'''

from configsys import layers
from configsys.config import Config


def cfg(repo_text, user_text=None):
    ls = [layers.Layer('config.hu', 'repo', layers.materialize_string(repo_text))]
    if user_text is not None:
        ls.append(layers.Layer('user.hu', 'user', layers.materialize_string(user_text)))
    return Config(ls)


REPO = '{ profiles: { dev: [ btop  fzf ]  base: [ git  curl ] } }'


def test_profile_relation_tracked_shadowed_base():
    # relation reads how the layer chain composes a profile (still live for repo<plugin layering).
    assert cfg(REPO).profile_relation('dev') == 'base'                                  # single (repo) def
    assert cfg(REPO, '{ profiles: { dev: [ +dev  x ] } }').profile_relation('dev') == 'tracked'
    assert cfg(REPO, '{ profiles: { dev: [ x  y ] } }').profile_relation('dev') == 'shadowed'

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
    # v3: the left pane is a FLAT browse list of the shipped repo/plugin profiles — no layer group
    # headers, plus the two keyword lenses.
    from configsys.tui import menu
    ctx = _rctx(tmp_path)
    ps = menu.ProfileScreen(ctx)
    v = ps.visible_pnodes()
    assert not any(ps.is_group_header(nd) for nd in v)         # no group headers (flat)
    names = {nd[0] for nd in v}
    assert 'finders' in names and 'languages' in names        # repo browse profiles present
    assert '!all' in names and '!uninstall' in names          # the two keyword browse lenses show


def test_where_profile_report(tmp_path):
    from configsys.app import where_profile_report
    ctx = _rctx(tmp_path)
    assert where_profile_report(ctx, 'no-such-profile') is None
    # a shipped repo browse profile: the report names it, where it's defined, and its members
    txt = '\n'.join(where_profile_report(ctx, 'finders'))
    assert 'browse lens' in txt and 'config.hu (repo)' in txt
    assert 'members' in txt and 'fd' in txt                    # finders includes fd


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
