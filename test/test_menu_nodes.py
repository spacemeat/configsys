'''Components-tree row -> component mapping. A child UNIT under an expanded group must report its
OWN component (so subcomponents get their own description, not the parent's), and the description
map is built once from ctx.routes (which rebuilds a Resolver on every access — never per frame).'''

import types

from configsys.tui import menu
from configsys.tui.menu import COMPONENT, LINK, PROFILE, UNIT, Node


def _member(comp):
    return types.SimpleNamespace(component=types.SimpleNamespace(comp=comp, driver='apt'))


def test_node_component_uses_the_rows_own_component():
    # a group (gcc-13) with two distinct sub-units
    parent = Node(COMPONENT, 'c:dev:gcc-13', 'gcc-13', 1,
                  [_member('gcc-13-core'), _member('gcc-13-cxx')], expandable=True)
    child = Node(UNIT, 'u:dev:gcc-13:apt\\gcc-13-cxx', 'gcc-13-cxx', 2, [_member('gcc-13-cxx')])
    assert menu._node_component(parent) == 'gcc-13'          # group -> the id name (the aggregate)
    assert menu._node_component(child) == 'gcc-13-cxx'       # child unit -> its OWN component
    # a single-unit leaf (kind UNIT, id c:...) -> its own component
    leaf = Node(UNIT, 'c:dev:btop', 'btop', 1, [_member('btop')])
    assert menu._node_component(leaf) == 'btop'
    # profile / link rows have no component
    assert menu._node_component(Node(PROFILE, 'p:dev', 'dev', 0, [])) is None
    assert menu._node_component(Node(LINK, 'l:dev:web', 'web', 1, [])) is None
    assert menu._node_component(None) is None


def test_describe_maps_name_to_description():
    class _Comp:
        def __init__(self, d):
            self.description = d

    class _Routes:
        accesses = 0
        @property
        def components(self):
            type(self).accesses += 1
            return {'btop': _Comp('a process monitor'), 'git': _Comp('')}

    routes = _Routes()
    ctx = types.SimpleNamespace(routes=routes)
    assert menu._describe(ctx) == {'btop': 'a process monitor', 'git': ''}
    assert _Routes.accesses == 1                             # one ctx.routes hit per build (cached by caller)


def test_describe_survives_a_routes_error():
    class _Boom:
        @property
        def components(self):
            raise RuntimeError('resolve failed')
    assert menu._describe(types.SimpleNamespace(routes=_Boom())) == {}
