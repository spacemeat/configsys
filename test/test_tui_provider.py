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
    node = types.SimpleNamespace(id=f'c:dev:{name}')
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
