'''Regression tests for the TUI audit fixes (batch C): untrusted group status, bulk-stage safety,
the to-do view's routing statuses, the glue attr axis, Profiles `where`, the System Updates
refresh/clear rules, ProfileScreen._resolve thread-safety, screen-first key dispatch, cross-layer
key lint (rebind-wins), help labels, ignored-orphan dimming, and the Screen-protocol cleanup.'''

import threading
import time
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from _render_harness import RecordingPalette, build_ctx
from configsys import layers, sysupdates
from configsys.componentObj import ResolvedComponent
from configsys.config import Config
from configsys.installState import ComponentState
from configsys.sysupdates import UpdateRow
from configsys.tui import menu
from configsys.tui.keyspec import (ROUTER_ACTIONS, KNOWN_ACTIONS, Keymap, config_keys, lint_keys,
                                   lint_merged, merge_layer_keys)
from configsys.tui.surface import BufferSurface


@pytest.fixture(scope='module')
def ctx(tmp_path_factory):
    return build_ctx(tmp_path_factory.mktemp('fixc'))


def cs(key, status='installed', requested_as=None, **kw):
    drv, comp = key.split('\\', 1)
    rc = ResolvedComponent(key=key, driver=drv, comp=comp, fields={'name': comp},
                           requested_as=set(requested_as if requested_as is not None else [comp]))
    base = dict(component=rc, managed=False, error=None, lock_source=None, supported=True,
                present=True, installed_version='1', latest_version='1', locked=False)
    if status == 'missing':
        base.update(present=False, installed_version=None, latest_version='2')
    elif status == 'outdated':
        base.update(latest_version='2')
    elif status == 'untrusted':
        base.update(supported=False, present=False, installed_version=None, latest_version=None,
                    untrusted=True, error='driver "x" comes from a plugin you haven\'t trusted yet')
    elif status == 'unsupported':
        base.update(supported=False, present=False, installed_version=None, latest_version=None,
                    error='driver "x" not yet supported')
    base.update(kw)
    return ComponentState(**base)


def _cfg(*texts):
    roles = ['repo'] + ['user'] * (len(texts) - 1)
    return Config([layers.Layer(f'l{i}.hu', roles[i], layers.materialize_string(t))
                   for i, t in enumerate(texts)])


def _repo_text():
    import os
    return open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.hu'),
                encoding='utf-8').read()


# -- 1. Node.status: 'untrusted' -----------------------------------------------

def test_untrusted_unit_and_group_status():
    states = {'plug\\tool': cs('plug\\tool', 'untrusted'),
              'apt\\btop': cs('apt\\btop', 'installed')}
    ms = menu.MenuState(states, [('p', ['tool', 'btop'])])
    by = {n.label: n for n in ms._all_nodes()}
    assert by['tool'].status == 'untrusted'          # the leaf reads like ComponentState.status
    assert states['plug\\tool'].status == 'untrusted'
    assert by['p'].status == 'installed'             # an untrusted member doesn't turn its group 'error'


def test_mixed_untrusted_and_unsupported_reads_unsupported():
    states = {'plug\\a': cs('plug\\a', 'untrusted', requested_as=['x']),
              'nope\\b': cs('nope\\b', 'unsupported', requested_as=['x'])}
    ms = menu.MenuState(states, [('p', ['x'])])
    assert {n.label: n for n in ms._all_nodes()}['x'].status == 'unsupported'


def test_real_error_still_turns_group_error():
    states = {'plug\\a': cs('plug\\a', 'untrusted'), 'apt\\b': cs('apt\\b', error='probe failed')}
    ms = menu.MenuState(states, [('p', ['a', 'b'])])
    assert {n.label: n for n in ms._all_nodes()}['p'].status == 'error'


# -- 2. stage_all: never flips a staged remove; only tracked units; extras leak ---

def test_stage_all_keeps_a_seeded_remove_and_skips_untracked():
    states = {'apt\\old': cs('apt\\old', 'outdated'),          # tracked, outdated, queued for uninstall
              'apt\\new': cs('apt\\new', 'missing'),           # tracked, missing
              'apt\\extra': cs('apt\\extra', 'outdated'),      # installed-but-UNtracked extra
              'apt\\dep': cs('apt\\dep', 'missing', requested_as=['new'])}   # a tracked pick's dep
    ms = menu.MenuState(states, [('p', ['old', 'new'])])
    ms._req_sig = frozenset({'old', 'new'})
    ms.staged['apt\\old'] = 'remove'                           # as _seed_uninstall would
    n = ms.stage_all('install')
    assert ms.staged['apt\\old'] == 'remove'                   # NOT flipped to 'upgrade'
    assert ms.staged['apt\\new'] == 'install' and ms.staged['apt\\dep'] == 'install'
    assert 'apt\\extra' not in ms.staged                       # not part of this machine's picks
    assert n == 2
    assert ms.stage_all('upgrade') == 0                         # nothing new to stage


def test_stage_all_unrestricted_without_req_sig():
    ms = menu.MenuState({'apt\\a': cs('apt\\a', 'missing')}, [('p', ['a'])])
    assert ms.stage_all('install') == 1                        # a direct-built MenuState: no filter


def test_mode_switch_drops_installed_tracked_extras(monkeypatch):
    def fake_model(ctx, cfg, states, mode, caches=None):
        states = dict(states)
        if mode == 'installed+tracked':
            states['apt\\extra'] = cs('apt\\extra', 'outdated')
        return states, [('p', ['a'] + (['extra'] if 'apt\\extra' in states else []))], None
    monkeypatch.setattr(menu, '_components_model', fake_model)
    ms = menu.MenuState({'apt\\a': cs('apt\\a', 'missing')}, [('p', ['a'])])
    ms.mode, ms._req_sig, ms._overlay_caches = 'tracked', frozenset({'a'}), {}
    ms.descriptions = {}
    it, states, _l, _t = menu._switch_mode(None, None, ms, 'installed+tracked')
    assert 'apt\\extra' in states and it._extra_keys == {'apt\\extra'}
    todo, states2, _l, _t = menu._switch_mode(None, None, it, 'to-do')
    assert 'apt\\extra' not in states2 and 'apt\\extra' not in todo.states   # no lingering extra
    assert todo.stage_all('upgrade') == 0                                     # ...for U to sweep up
    # an extra the user STAGED survives the switch (dropping it would discard their mark silently)
    it2, _s, _l, _t = menu._switch_mode(None, None, todo, 'installed+tracked')
    it2.staged['apt\\extra'] = 'remove'
    back, states3, _l, _t = menu._switch_mode(None, None, it2, 'tracked')
    assert 'apt\\extra' in states3 and back.staged['apt\\extra'] == 'remove'
    assert back._extra_keys == {'apt\\extra'}


# -- 3. to-do view: routing statuses count -------------------------------------

class _FakeCfg:
    def __init__(self, picks):
        self._picks = picks

    def requested(self):
        return list(self._picks)

    def uninstall_queue(self):
        return set()

    def profile_names(self):
        return []


def test_todo_view_shows_switch_unmet_dangling():
    states = {'apt\\sw': cs('apt\\sw', 'missing', route_status='switch'),
              'apt\\um': cs('apt\\um', 'missing', route_status='unmet'),
              'apt\\dg': cs('apt\\dg', 'installed', route_status='dangling'),
              'apt\\ok': cs('apt\\ok', 'installed'),
              'apt\\mi': cs('apt\\mi', 'missing')}
    ctx = SimpleNamespace(routes=SimpleNamespace(components={}), _sysupd_groups=None)
    _st, layouts, transitive = menu._components_model(
        ctx, _FakeCfg(['sw', 'um', 'dg', 'ok', 'mi']), states, 'to-do')
    shown = set(transitive['(other)'])
    assert shown == {'sw', 'um', 'dg', 'mi'}               # every not-green pick; 'ok' omitted
    assert states['apt\\sw'].status == 'switch'            # (routing status outranks 'missing')


# -- 4. glue on the role attr axis ----------------------------------------------

def test_glue_is_a_role_attr_and_every_via_attr_has_an_axis():
    from configsys.routes import _VIA_ATTR
    assert menu._ATTR_AXIS_OF['glue'] == 'role'
    for tag in _VIA_ATTR.values():
        assert tag.lower() in menu._ATTR_AXIS_OF, tag


# -- 5. Profiles `where` is wired ----------------------------------------------

def test_profiles_where_is_a_known_bound_action():
    assert 'where' in KNOWN_ACTIONS['profiles']
    c = _cfg(_repo_text())
    km = Keymap(config_keys(c))
    assert km.action_for('profiles', ord('w')) == 'where'
    assert lint_keys(c._layers) == []                       # no clash in the shipped keymap
    assert 'profile' in Keymap.label('profiles', 'where')   # a page-specific help label


def test_profiles_where_opens_the_overlay(ctx):
    from configsys.tui.screens.profiles import ProfilesScreen
    scr = ProfilesScreen(ctx, menu._sample_profiles_state(ctx))
    w = next(k for k in range(32, 127) if menu._KEYMAP.action_for('profiles', k) == 'where')
    scr.model.focus = 'right'                                # table: the cursor COMPONENT
    comp = scr.model.vcatalog()[scr.model.rcur]
    intent = scr.handle(w, ctx, None, None)
    assert intent.open_where is not None and intent.open_where[1] == comp
    scr.model.focus = 'left'                                 # browse pane: the profile's provenance
    prof = scr.model.cur_profile()
    intent = scr.handle(w, ctx, None, None)
    assert prof and intent.open_where is not None and intent.open_where[1] == prof


# -- 6. System Updates: R re-scans; clear is all-or-nothing ----------------------

def _su_groups():
    return {'apt': [UpdateRow('apt', 'linux-image-generic', '7.0', '7.1', False, 'kernel'),
                    UpdateRow('apt', 'coreutils', '8.32-1', '8.32-2', False, 'core'),
                    UpdateRow('apt', 'libc6', '2.39-1', '2.39-2', False, 'core'),
                    UpdateRow('apt', 'htop', '3.0', '3.2', True, 'apps'),
                    UpdateRow('apt', 'jq', '1.6', '1.7', True, 'apps')]}


def _su_menu():
    su_states, su_layouts, su_trans = sysupdates.tree_injection(_su_groups())
    states = {'apt\\a': cs('apt\\a', 'missing'), **su_states}
    ms = menu.MenuState(states, [('p', ['a'])] + su_layouts, {'p': ['a'], **su_trans})
    for n in ms._all_nodes():
        if n.expandable:
            n.expanded = True
    ms._refresh()
    return ms


def test_clear_inside_system_updates_unstages_all_of_them():
    ms = _su_menu()
    assert ms.stage_system_updates() == 5
    ms.staged['apt\\a'] = 'install'
    ms.cursor = next(i for i, n in enumerate(ms.rows) if n.label == 'coreutils')   # one SU leaf
    ms.unstage()
    assert ms.staged == {'apt\\a': 'install'}               # every SU row went, the real op stayed


def test_clear_key_in_su_subtree_notes_all_or_nothing(ctx):
    from configsys.tui.screens.components import ComponentsScreen
    ms = _su_menu()
    ms.stage_system_updates()
    ms.cursor = next(i for i, n in enumerate(ms.rows) if n.label == 'htop')
    scr = ComponentsScreen(ctx, ms)
    c = next(k for k in range(32, 127) if menu._KEYMAP.action_for('components', k) == 'clear')
    intent = scr.handle(c, ctx, None, None, None, None)
    assert not any(menu._is_system_update(ms.states[k]) for k in ms.staged)
    assert intent.note and 'all or nothing' in intent.note


def _patch_refresh(monkeypatch, ctx, calls):
    from configsys import app
    from configsys.tui.screens import components as comp_mod
    monkeypatch.setattr(comp_mod, 'suspended', lambda _s: nullcontext())
    monkeypatch.setattr(comp_mod.curses, 'flushinp', lambda: None)
    monkeypatch.setattr(app, 'cmd_refresh', lambda c, a: calls.append('refresh'))
    monkeypatch.setattr('builtins.input', lambda *a: '')
    monkeypatch.setattr(sysupdates, 'start_scan', lambda c: calls.append('start_scan'))

    def fake_reload(c, ms, dirty):
        calls.append(('reload', getattr(c, '_sysupd_groups', 'unset')))
        return (ms, None, None, ms.states, ())
    monkeypatch.setattr(comp_mod, '_reload', fake_reload)


def test_refresh_invalidates_and_rescans_system_updates(ctx, monkeypatch):
    from configsys.tui.screens.components import ComponentsScreen
    calls = []
    _patch_refresh(monkeypatch, ctx, calls)
    monkeypatch.setattr(ctx, '_sysupd_groups', _su_groups(), raising=False)
    ms = _su_menu()
    ms.stage_system_updates()
    scr = ComponentsScreen(ctx, ms)
    r = next(k for k in range(32, 127) if menu._KEYMAP.action_for('components', k) == 'refresh')
    intent = scr.handle(r, ctx, BufferSurface(40, 120), RecordingPalette(), None, None)
    # the stale scan is dropped BEFORE the reload (no stale rows re-injected), re-gathered after it
    assert calls == ['refresh', ('reload', None), 'start_scan']
    assert ctx._sysupd_groups is None and sysupdates.cached_total(ctx) == 0   # header chip: no stale count
    assert 'system update' in intent.note                    # says the staged SU marks went with it


def test_execute_rescans_system_updates(ctx, monkeypatch):
    from configsys import rebootcheck
    from configsys.actions import OpOutcome
    from configsys.tui.screens import components as comp_mod
    calls = []
    _patch_refresh(monkeypatch, ctx, calls)
    monkeypatch.setattr(ctx, '_sysupd_groups', _su_groups(), raising=False)
    monkeypatch.setattr(rebootcheck, 'reboot_pending', lambda c: (False, ''))
    monkeypatch.setattr(comp_mod, '_confirm_and_execute', lambda *a: (
        True, 'done', [OpOutcome('upgrade', 'system-updates\\apt', 'apt', True, '')]))
    ms = _su_menu()
    ms.stage_system_updates()
    scr = comp_mod.ComponentsScreen(ctx, ms)
    x = next(k for k in range(32, 127) if menu._KEYMAP.action_for('components', k) == 'execute')
    scr.handle(x, ctx, None, None, None, None)
    assert calls == [('reload', None), 'start_scan']


# -- 7. ProfileScreen._resolve is thread-safe -----------------------------------

class _SlowRoutes:
    def __init__(self):
        self.active = 0
        self.peak = 0
        self.guard = threading.Lock()

    def candidates(self, name):
        with self.guard:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(0.0005)
        with self.guard:
            self.active -= 1
        return [{'default': True, 'via': f'via-{name}', 'pinned': False}]


def _bare_profile_screen(routes):
    ps = menu.ProfileScreen.__new__(menu.ProfileScreen)
    ps.ctx = SimpleNamespace(routes=routes)
    ps._res = {}
    ps._res_lock = threading.Lock()
    return ps


def test_resolve_concurrent_threads_serialize_and_agree():
    routes = _SlowRoutes()
    ps = _bare_profile_screen(routes)
    names = [f'c{i}' for i in range(40)]
    errs = []

    def work():
        try:
            for n in names:
                assert ps._resolve(n) == (True, f'via-{n}', False)
        except Exception as e:                               # noqa: BLE001
            errs.append(e)
    ts = [threading.Thread(target=work) for _ in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errs
    assert routes.peak == 1                                  # one Resolver is never driven concurrently
    assert set(ps._res) == set(names)


def test_resolve_never_overwrites_a_primed_value_or_caches_across_a_routes_swap():
    routes = _SlowRoutes()
    ps = _bare_profile_screen(routes)
    orig = routes.candidates

    def priming_mid_resolve(name):                         # a priming lands while a resolve is in flight
        ps._res[name] = (True, 'primed', True)
        return orig(name)
    routes.candidates = priming_mid_resolve
    assert ps._resolve('x') == (True, 'primed', True)        # setdefault: the primed value wins
    assert ps._res['x'] == (True, 'primed', True)

    new_routes = _SlowRoutes()

    def swap_mid_resolve(name):                            # ctx.routes rebuilt while resolving
        ps.ctx.routes = new_routes
        ps._res_rid = id(new_routes)
        return orig(name)
    routes.candidates = swap_mid_resolve
    ps._res.clear()
    assert ps._resolve('y') == (True, 'via-y', False)        # returned, but NOT cached for the new routes
    assert 'y' not in ps._res


# -- 8. keys: a screen's own scope wins, even over router keys -------------------

def _old_route(km, screen, ch):
    '''The pre-fix router order: global quit/quit-force/issues/help, then `screens`, then the page.'''
    g = km.action_for('global', ch)
    if g in ROUTER_ACTIONS:
        return g, None
    return None, km.screen_for(ch)


def test_default_keymap_routes_exactly_as_before():
    km = Keymap(config_keys(_cfg(_repo_text())))
    for screen in ('components', 'profiles', 'plugins', 'glue', 'dotfiles', 'config', 'theme'):
        for ch in list(range(0, 600)):
            assert menu._route_key(km, screen, ch) == _old_route(km, screen, ch), (screen, ch)


def test_screen_binding_wins_over_router_and_screen_keys():
    km = Keymap({'global': {'quit': 'q', 'quit-force': 'Q', 'issues': '!', 'help': '?', 'down': 'j'},
                 'screens': {'components': '1', 'profiles': '2'},
                 'components': {'where': 'q', 'op-install': '2', 'help': 'H', 'quit': 'Z'}})
    assert menu._route_key(km, 'components', ord('q')) == (None, None)       # -> the screen's `where`
    assert menu._route_key(km, 'components', ord('2')) == (None, None)       # -> its op-install
    assert menu._route_key(km, 'components', ord('H')) == ('help', None)     # page-bound help works
    assert menu._route_key(km, 'components', ord('Z')) == ('quit', None)     # page-bound quit works
    assert menu._route_key(km, 'components', ord('Q')) == ('quit-force', None)   # untouched global
    assert menu._route_key(km, 'components', ord('j')) == (None, None)       # nav -> handle
    assert menu._route_key(km, 'profiles', ord('q')) == ('quit', None)       # other pages unchanged
    assert menu._route_key(km, 'profiles', ord('2')) == (None, 'profiles')
    assert menu._route_key(km, 'profiles', ord('1')) == (None, 'components')


# -- 9. keys lint across layers + rebind-wins merge ------------------------------

_REPO_KEYS = ('{ keys: { global: { quit: q  issues: "!" }  screens: { components: "1" } '
              '  components: { op-install: i  where: w  lock: [ L  l ] } } }')


def test_higher_layer_rebind_takes_the_key_from_the_lower_action():
    c = _cfg(_REPO_KEYS, '{ keys: { components: { where: i  lock: l } } }')
    merged = config_keys(c)
    assert merged['components']['where'] == 'i'
    assert 'op-install' not in merged['components']          # its only key was taken -> unbound
    km = Keymap(merged)
    assert km.action_for('components', ord('i')) == 'where'  # deterministic: the user's rebind wins
    assert km.action_for('components', ord('L')) is None      # the higher layer replaced lock's keys
    assert km.keys_for('components', 'lock') == [ord('l')]
    warns = lint_keys(c._layers)
    assert any("takes the key from 'op-install'" in w and 'now unbound' in w for w in warns), warns
    assert all('l1.hu' in w for w in warns if 'takes the key' in w)   # provenance = the rebinding file


def test_partial_steal_keeps_the_lower_actions_other_keys():
    c = _cfg('{ keys: { global: { quit: q }  components: { lock: [ L  l ]  where: w } } }',
             '{ keys: { components: { where: l } } }')
    merged = config_keys(c)
    assert merged['components']['lock'] == ['L']
    assert any("takes the key from 'lock'" in w and 'unbound' not in w for w in lint_keys(c._layers))


def test_lint_merged_flags_a_plain_merge_duplicate_and_a_quit_lockout():
    dup = lint_merged({'global': {'quit': 'q'},                # a merged map with a same-scope clash
                       'components': {'op-install': 'i', 'where': 'i'}})
    assert any("'i' bound to both 'op-install' and 'where'" in w for w in dup), dup
    c = _cfg(_REPO_KEYS, '{ keys: { components: { where: i } } }')
    assert not lint_merged(c.keys())                          # Config.keys() applies rebind-wins too
    lock = lint_merged({'global': {'quit': 'q', 'quit-force': 'Q'},
                        'profiles': {'claim': 'q', 'mark-all-seen': 'Q'}})
    assert any('no way to quit' in w for w in lock)
    assert not lint_merged({'global': {'quit': 'q', 'quit-force': 'Q'},
                            'profiles': {'claim': 'q', 'quit': 'x'}})   # its own quit key: fine


def test_merge_without_conflicts_matches_config_keys():
    c = _cfg(_repo_text(), '{ keys: { global: { quit: [ q  "ctrl-c" ] } screens: { theme: t } } }')
    assert merge_layer_keys(c._layers) == c.keys()
    assert lint_keys(c._layers) == []


# -- 10/11. help labels -----------------------------------------------------------

def test_issues_label_has_no_hardcoded_key_and_follows_a_rebind():
    km = Keymap({'global': {'issues': 'E', 'quit': 'q'}})
    rows = dict((label, keys) for keys, label in km.help_rows('components'))
    assert 'show issues' in rows and rows['show issues'] == 'E'
    assert not any('(!)' in label for label in rows)


def test_help_rows_include_page_down_and_page_up():
    km = Keymap(config_keys(_cfg(_repo_text())))
    labels = [label for _k, label in km.help_rows('components')]
    assert 'page down' in labels and 'page up' in labels
    assert labels.index('page down') < labels.index('page up')


# -- 12. Profiles overlay: ignored orphans are dimmed --------------------------------

def _orphan_row_role(ctx, ps):
    '''Paint the Profiles screen and return the palette element of the inst'd ⊙ glyph on the cursor
    row (an installed-but-untracked component).'''
    from configsys.tui.screens.profiles import ProfilesScreen
    scr = ProfilesScreen(ctx, ps)
    vm = scr.build_vm(ps.ctx, (40, 160))
    vm.note = ''
    surf = BufferSurface(40, 160)
    scr.draw(surf, RecordingPalette(gradient=False), vm)
    name = ps.vcatalog()[ps.rcur]
    for y, r in enumerate(surf.text_rows()):                 # the catalog row: the name, then its ⊙
        at = r.find(name)                                     # (left-pane ⊙N badges sit before it)
        if at < 0:
            continue
        xs = [x for (yy, x), cell in sorted(surf.cells.items())
              if yy == y and x > at and cell.char == '⊙']
        if xs:
            return surf.cells[(y, xs[0])].attr.token[2]
    raise AssertionError(f'no ⊙ row for {name}')


def test_ignored_orphan_is_dimmed(ctx):
    from configsys.orphans import Orphan
    ps = menu._sample_profiles_state(ctx)
    track = ps.ctx.config.included()
    uq = ps.ctx.config.uninstall_queue()
    vc = ps.vcatalog()
    i = next(i for i, n in enumerate(vc)
             if ps.install_state(n) == 'all' and n not in track and n not in uq)
    ps.rcur = i
    name = vc[i]
    assert _orphan_row_role(ctx, ps) == 'orphan_lurking'      # an un-ignored ⊙ keeps its colour
    ps._overlay = (frozenset(), {name: Orphan('apt', name, '1', name, 'known', ignored=True)},
                   frozenset())
    assert _orphan_row_role(ctx, ps) == 'info_dim'           # the scan says ignored -> dimmed
    ps._overlay = (frozenset(), {}, frozenset())
    ps.ctx.config.orphans_ignore = lambda: [name[:2] + '*']  # a config glob, before the scan lands
    assert _orphan_row_role(ctx, ps) == 'info_dim'


# -- 13. the Screen protocol cleanup --------------------------------------------------

def test_intent_has_no_dead_handled_field_and_no_size():
    from configsys.tui import screens
    from configsys.tui.screens.base import Intent
    assert 'handled' not in Intent.__dataclass_fields__
    assert not hasattr(screens, 'Size')


# -- follow-ups: `map` settings, --pretend notes ---------------------------------------------

def test_map_setting_displays_like_a_list():
    assert menu._setting_str('map', ['nvim=/opt/nvim', 'zig=/opt/zig'], 'locations') == \
        'nvim=/opt/nvim zig=/opt/zig'
    assert menu._setting_str('map', [], 'locations') == '(unset — built-in default)'
    assert menu._setting_str('map', {'b': '/y', 'a': '/x'}, 'locations') == 'a=/x b=/y'


def test_pretend_note_only_rewrites_attempted_writes_under_pretend():
    dry = SimpleNamespace(runner=SimpleNamespace(pretend=True))
    real = SimpleNamespace(runner=SimpleNamespace(pretend=False))
    assert menu._pretend_note(real, 'x set', True) == 'x set'
    assert menu._pretend_note(dry, 'x set', False) == 'x set'          # no write attempted
    assert menu._pretend_note(dry, 'x set', True) == '[pretend] not saved (--pretend) — would: x set'
    assert menu._pretend_note(dry, 'a: [pretend] not saved', True) == 'a: [pretend] not saved'


def _key_for(scope, action):
    return next(k for k in range(1, 400) if menu._KEYMAP.action_for(scope, k) == action)


def test_config_edit_under_pretend_says_not_saved(ctx):
    from configsys.tui.screens.config import ConfigScreen
    assert ctx.runner.pretend                                 # the harness ctx is --pretend
    scr = ConfigScreen(ctx, menu.ConfigScreen(ctx))
    cs = scr.model
    cs.cur = next(i for i, k in enumerate(cs.keys) if cs.settings[k]['kind'] == 'bool')
    key = cs.keys[cs.cur]
    before = cs.settings[key]['value']
    intent = scr.handle(_key_for('config', 'confirm'), ctx, None, None)
    assert intent.note.startswith('[pretend] not saved') and key in intent.note
    cs.reload()
    assert cs.settings[key]['value'] == before                # nothing was written


def test_profiles_track_under_pretend_says_not_saved(ctx):
    from configsys.tui.screens.profiles import ProfilesScreen
    scr = ProfilesScreen(ctx, menu._sample_profiles_state(ctx))
    scr.model.focus = 'right'
    intent = scr.handle(_key_for('profiles', 'track-one'), ctx, None, None)
    assert intent.note == '[pretend] not saved (--pretend)'   # not a misleading "no change"


def test_theme_edit_under_pretend_says_not_saved(ctx, monkeypatch):
    from configsys.tui.screens import theme as theme_mod
    from configsys.tui.screens.theme import ThemeScreen
    monkeypatch.setattr(theme_mod, 'Palette', lambda *_a, **_k: RecordingPalette())   # no curses here
    scr = ThemeScreen(ctx, menu.ThemeScreen(ctx), sample_ms=menu._sample_components_state())
    intent = scr.handle(_key_for('theme', 'gradient-toggle'), ctx, None, RecordingPalette())
    assert intent.note.startswith('[pretend] not saved') and 'gradient' in intent.note
