'''TUI provider picker (`P`): choose which component satisfies a capability with >1 provider, and
write a capability->provider pin. Exercises the pure helpers + the picker's selection flow against
real base routes (cuda-toolkit-11 opt-in / cuda-toolkit-12 default, both `provides: cuda-toolkit`).'''

import types

from configsys import plugins
from configsys.app import Context, build_parser
from configsys.tui import menu


class _Scr:
    def __init__(self, keys):
        self._keys = list(keys)

    def getmaxyx(self):
        return (24, 80)

    def addstr(self, *a):
        pass

    def refresh(self):
        pass

    def getch(self):
        return self._keys.pop(0)


class _Pal:
    def get(self, _name):
        return 0


def _ctx(tmp_path):
    return Context(build_parser().parse_args(['--home', str(tmp_path), '--os', 'pop', 'inspect']))


def _row(name):
    state = types.SimpleNamespace(component=types.SimpleNamespace(comp=name))
    node = types.SimpleNamespace(kind=menu.UNIT, id=f'c:dev:{name}', members=[state])
    return types.SimpleNamespace(cur=lambda: node)


# -- pure helpers ---------------------------------------------------------

def test_providers_and_capability_choices(tmp_path):
    ctx = _ctx(tmp_path)
    assert menu._providers_of(ctx.routes, 'cuda-toolkit') == ['cuda-toolkit-11', 'cuda-toolkit-12']
    # from the provider's row, its provided capability is the choice
    ch = menu._capability_choices(ctx.routes, 'cuda-toolkit-12')
    assert ch == [('cuda-toolkit', ['cuda-toolkit-11', 'cuda-toolkit-12'])]
    # a component with no multi-provider capability -> nothing to pick
    assert menu._capability_choices(ctx.routes, 'git') == []


# -- picker writes a provider-pin ----------------------------------------

def test_pick_provider_writes_a_capability_pin(tmp_path):
    ctx = _ctx(tmp_path)
    ENTER = 10
    # single capability -> straight to the provider list; start sits on the default (cuda-toolkit-12,
    # index 1). 'k' moves up to cuda-toolkit-11 (index 0), enter selects.
    scr = _Scr([ord('k'), ENTER])
    changed, note, deferred = menu._pick_provider(scr, _Pal(), _row('cuda-toolkit-12'), ctx)
    assert changed
    assert 'cuda-toolkit' in note and 'cuda-toolkit-11' in note
    assert 'promote' in (deferred or '')                         # portability hint deferred to exit
    ctx.invalidate()
    assert ctx.config.pins().get('cuda-toolkit') == 'cuda-toolkit-11'   # the provider-pin landed


def test_pick_provider_noop_when_choosing_current(tmp_path):
    ctx = _ctx(tmp_path)
    ENTER = 10
    scr = _Scr([ENTER])                                          # start is already the current default
    changed, note, _d = menu._pick_provider(scr, _Pal(), _row('cuda-toolkit-12'), ctx)
    assert not changed and 'already provided by' in note
    assert not plugins.read_pins(str(ctx.paths.user_config_file))   # nothing written


def test_pick_provider_declines_a_row_without_alternatives(tmp_path):
    ctx = _ctx(tmp_path)
    changed, note, _d = menu._pick_provider(_Scr([]), _Pal(), _row('git'), ctx)
    assert not changed and 'no capability with alternative providers' in note


# -- unified `m`: the choices chooser folds the method picker + the provider picker -----------

def test_choices_single_method_axis_opens_the_method_picker(tmp_path):
    ctx = _ctx(tmp_path)
    ENTER = 10
    # steam: 2 methods, no multi-provider cap -> a single (method) axis -> straight to the method popup
    changed, note, _d = menu._pick_choices(_Scr([ord('j'), ENTER]), _Pal(), _row('steam'), ctx)
    assert changed and 'flatpak' in note
    ctx.invalidate()
    assert ctx.config.pins().get('steam') == 'flatpak'           # wrote a binding-pin


def test_choices_single_provider_axis_opens_the_provider_picker(tmp_path):
    ctx = _ctx(tmp_path)
    ENTER = 10
    # cuda-toolkit-12: 1 method but provides a 2-provider cap -> a single (provider) axis
    changed, note, _d = menu._pick_choices(_Scr([ord('k'), ENTER]), _Pal(), _row('cuda-toolkit-12'), ctx)
    assert changed and 'cuda-toolkit-11' in note
    ctx.invalidate()
    assert ctx.config.pins().get('cuda-toolkit') == 'cuda-toolkit-11'   # wrote a provider-pin


def test_capability_choices_surface_the_winning_bindings_requires(tmp_path, monkeypatch):
    # the blender case: a variant's SDK need (cuda-toolkit) is declared on its WINNING binding, not
    # the component. The chooser must still surface the provider choice from the component's own row.
    # (synthesize the winner so the test doesn't depend on the blender plugin being synced here.)
    import types
    import configsys.resolve as resolve
    ctx = _ctx(tmp_path)
    won = types.SimpleNamespace(details={'requires': ['cuda-toolkit']})
    monkeypatch.setattr(resolve, '_select', lambda *a, **k: (won, None, ''))
    caps = dict(menu._capability_choices(ctx.routes, 'git'))   # git has no component-level requires
    assert caps.get('cuda-toolkit') == ['cuda-toolkit-11', 'cuda-toolkit-12']


def test_choices_with_no_axis_is_a_noop(tmp_path):
    ctx = _ctx(tmp_path)                                          # zsh: one method, no cap -> nothing
    changed, note, _d = menu._pick_choices(_Scr([]), _Pal(), _row('zsh'), ctx)
    assert not changed and 'nothing to choose' in note


def test_choices_multi_axis_asks_which_to_change_then_dispatches(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    ENTER = 10
    # give steam a second (provider) axis so the chooser must first ask WHICH axis to change
    monkeypatch.setattr(menu, '_capability_choices',
                        lambda routes, name: [('cuda-toolkit', ['cuda-toolkit-11', 'cuda-toolkit-12'])])
    # top menu (axis 0 = install method, axis 1 = provider): pick axis 0, then move+select flatpak
    changed, note, _d = menu._pick_choices(_Scr([ENTER, ord('j'), ENTER]), _Pal(), _row('steam'), ctx)
    assert changed and 'flatpak' in note                         # dispatched into the method picker
    ctx.invalidate()
    assert ctx.config.pins().get('steam') == 'flatpak'


# -- ambient "where" panel: capability edges folded into the identity line (no extra row) -----

def test_edges_text_surfaces_the_capability_graph(tmp_path):
    ctx = _ctx(tmp_path)
    assert 'requires: cuda-toolkit (<12)' in menu._edges_text(ctx, 'cudnn-8')   # constraint edge
    assert 'provides: cuda-toolkit (12)' in menu._edges_text(ctx, 'cuda-toolkit-12')
    assert menu._edges_text(ctx, 'git') == ''                    # a plain tool has no edges


def test_identity_line_folds_edges_without_a_new_row(tmp_path):
    ctx = _ctx(tmp_path)
    il = menu._identity_line(_row('cuda-toolkit-12'), ctx, {'cuda-toolkit-12': 'CUDA 12'})
    assert 'cuda-toolkit-12 — CUDA 12' in il and 'provides: cuda-toolkit (12)' in il
    # a plain tool with no edges shows JUST its identity — no wasted content
    assert menu._identity_line(_row('git'), ctx, {'git': 'vcs'}) == ' git — vcs'


# -- `w` full-page: the shared where-report (CLI + TUI overlay) -----------------------------

def test_where_report_is_the_full_graph(tmp_path):
    from configsys.app import where_report
    ctx = _ctx(tmp_path)
    text = '\n'.join(where_report(ctx, 'cudnn-8'))
    assert 'requires    cuda-toolkit (<12)' in text        # the versioned edge
    assert 'bindings' in text                               # every binding, the winner marked
    assert 'on pop_os' in text and 'cuda-toolkit-11' in text  # resolves to -11 (constraint <12)
    assert where_report(ctx, 'no-such-component') is None   # unknown -> None (caller shows the message)


# -- row identity: a dependency unit resolves to ITS component, not its requester's ---------

def test_row_component_of_a_dependency_unit_is_the_dependency(tmp_path):
    '''Regression: a dep unit is grouped under its requester, so its id encodes the requester's name
    (`u:<profile>:blender:script\\cuda-toolkit-12`). _row_component must return the dep's OWN
    component (from its member), else `m`/`P` act on the requester (blender) — the reported bug.'''
    state = types.SimpleNamespace(component=types.SimpleNamespace(comp='cuda-toolkit-12'))
    dep = menu.Node(menu.UNIT, 'u:dev:blender:script\\cuda-toolkit-12', 'cuda-toolkit-12', 2, [state])
    assert menu._row_component(dep) == 'cuda-toolkit-12'          # the dep, not 'blender'

    # a single-unit leaf and a component-group row still read their name from the id
    leaf_state = types.SimpleNamespace(component=types.SimpleNamespace(comp='git'))
    leaf = menu.Node(menu.UNIT, 'c:dev:git', 'git', 1, [leaf_state])
    assert menu._row_component(leaf) == 'git'
    group = menu.Node(menu.COMPONENT, 'c:dev:blender', 'blender', 1, [], expandable=True)
    assert menu._row_component(group) == 'blender'
    assert menu._row_component(menu.Node(menu.PROFILE, 'p:dev', 'dev', 0, [])) is None
