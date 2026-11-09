'''review-2026-11-2 B16 — TUI correctness: the view survives every rebuild; the to-do view shows a pick
that isn't green; the methods line under a pin; "auto — unpin"; Components is read-only while curating
another machine; bulk notes come from results; a screen error never ends the session.'''

import types

import pytest

from _render_harness import build_ctx
from configsys.componentObj import ResolvedComponent
from configsys.installState import ComponentState
from configsys.tui import menu
from configsys.tui.screens.base import results_note
from configsys.tui.screens.components import ComponentsScreen


@pytest.fixture(scope='module')
def ctx(tmp_path_factory):
    return build_ctx(tmp_path_factory.mktemp('b16'))


def _st(key, comp, req, present, error=None):
    rc = ResolvedComponent(key=key, driver='apt', comp=comp, fields={'name': comp}, requested_as=set(req))
    return ComponentState(component=rc, supported=True, present=present,
                          installed_version='1' if present else None, latest_version='1', locked=False,
                          lock_source=None, error=error, scope='system')


def _key(scope, action):
    return next(k for k in range(32, 127) if menu._KEYMAP.action_for(scope, k) == action)


def test_filter_and_scroll_survive_a_rebuild():
    ms = menu._sample_components_state()
    ms.set_filter('b')
    ms.top = 2
    rows = [n.id for n in ms.rows]
    new = menu._rebuild_menu(ms, ms.states, ms.layouts, None, 'tracked')
    assert new.filter == 'b' and [n.id for n in new.rows] == rows and new.top == 2


def test_todo_shows_a_partial_pick_and_error_picks():
    states = {'apt\\virt-manager': _st('apt\\virt-manager', 'virt-manager', ['virt-manager'], True),
              'apt\\libvirt-service': _st('apt\\libvirt-service', 'libvirt-service', ['virt-manager'], False),
              'apt\\broken': _st('apt\\broken', 'broken', ['broken'], False, error='a route problem')}
    cfg = types.SimpleNamespace(requested=lambda: ['virt-manager', 'broken'], uninstall_queue=lambda: [],
                                profile_names=lambda: [], profile_own_components=lambda p: [])
    c = types.SimpleNamespace(routes=types.SimpleNamespace(components={}), _sysupd_groups=None)
    s2, layouts, trans = menu._components_model(c, cfg, states, 'to-do')
    ms = menu.MenuState(s2, layouts, trans)
    labels = {n.label for n in ms._all_nodes()}
    assert 'virt-manager' in labels and 'broken' in labels


def test_methods_line_under_a_pin_flags_the_auto_default(tmp_path):
    from configsys.routes import Resolver
    p = tmp_path / 'routes.hu'
    p.write_text('{ os: { linux: {}  debian: { using: linux  native: apt } }  components: { '
                 'bat: { install: [ { via: native } { via: cargo } ] }  cargo: { install: [ { via: native } ] } }'
                 '  drivers: { cargo: { requires: cargo } } }')
    r = Resolver(str(p), 'debian', '12', 'x86_64', pins={'bat': 'cargo'})
    cands = {c['via']: c for c in r.candidates('bat')}
    assert cands['cargo']['default'] and cands['cargo']['pinned']
    assert cands['native']['auto'] and not cands['cargo']['auto']
    why = menu._why(types.SimpleNamespace(routes=r), 'bat')
    assert why.startswith('pinned to cargo')


def test_unset_pin_removes_it_from_the_top_config(tmp_path):
    from configsys import actions, plugins
    from configsys.paths import Paths
    paths = Paths(env={'HOME': str(tmp_path)})
    paths.user_config_file.parent.mkdir(parents=True)
    paths.user_config_file.write_text('{ pins: { bat: cargo  fd: native } }\n')
    c = types.SimpleNamespace(paths=paths, runner=types.SimpleNamespace(pretend=False), config=None,
                              invalidate=lambda: None, invalidate_config=lambda: None)
    changed, where = actions.unset_pin(c, 'bat')
    assert changed and where == 'top config'
    assert plugins.read_pins(paths.user_config_file) == {'fd': 'native'}
    assert actions.unset_pin(c, 'bat')[0] is False


def test_components_is_read_only_while_curating_another_machine(ctx, monkeypatch):
    scr = ComponentsScreen(ctx, menu._sample_components_state())
    monkeypatch.setattr(ctx, 'curating_machine', lambda: 'laptop', raising=False)
    before = dict(scr.model.staged)
    intent = scr.handle(_key('components', 'op-install-all'), ctx, None, None, None, None)
    assert 'curating laptop' in intent.note and scr.model.staged == before


def test_results_note_reports_failures_and_pretend():
    live = types.SimpleNamespace(runner=types.SimpleNamespace(pretend=False))
    dry = types.SimpleNamespace(runner=types.SimpleNamespace(pretend=True))
    res = [('a', True, ''), ('fd-glue', False, 'no such shell'), ('c', True, '')]
    assert results_note(live, 'activated', res, what='snippet(s)') == \
        'activated 2 of 3 snippet(s) — fd-glue failed: no such shell'
    assert results_note(dry, 'activated', res[:1]).startswith('[pretend] nothing changed')
    assert results_note(live, 'activated', [], nothing='none') == 'none'


def test_rebuild_and_set_version_stage_on_a_present_unit():
    # G1 / §7.17: the `v` picker's rebuild + set-version rows stage on an installed, current unit
    states = {'source\\rg': _st('source\\rg', 'rg', ['rg'], True)}
    ms = menu.MenuState(states, [('p', ['rg'])])
    assert ms.stage_unit('source\\rg', 'install')
    assert ms.plan()[0][:2] == ('install', 'source\\rg')
    assert ms.stage_unit('source\\rg', 'set-version', '14.0.0')
    assert ms.plan_versions() == {'source\\rg': '14.0.0'}


def test_run_plan_takes_a_version_per_unit(tmp_path, monkeypatch):
    import configsys.drivers as drivers_mod
    from configsys import actions
    from configsys.paths import Paths
    from configsys.runner import Result as R
    got = {}

    class D:
        honors_scope = False
        def set_version(self, rc, v):
            got[rc.comp] = v
            return R('', 0)
        def get_version(self, rc):
            return None
    monkeypatch.setattr(drivers_mod, 'get_driver', lambda *a, **k: D())
    monkeypatch.setattr(actions, 'targets_version', lambda d: True)
    c = types.SimpleNamespace(runner=types.SimpleNamespace(pretend=False, end_sudo=lambda: None),
                              paths=Paths(env={'HOME': str(tmp_path)}))
    a = ResolvedComponent(key='pip\\a', driver='pip', comp='a', fields={})
    b = ResolvedComponent(key='pip\\b', driver='pip', comp='b', fields={})
    actions.run_plan(c, [('set-version', 'pip\\a', a), ('set-version', 'pip\\b', b)],
                     version={'pip\\a': '1.0', 'pip\\b': '2.0'}, on_line=lambda *_: None)
    assert got == {'a': '1.0', 'b': '2.0'}
