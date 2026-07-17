'''App-boundary parity: resolve the real config.hu profiles through BOTH resolver paths
(the live RouteResolver and the v2 V2Resolver behind the flag) and assert the app sees
identical units — same keys AND, for every unit in the closure, the same per-family install
signature. This exercises the full plumbing (engine facade, adapt, roots, the Context flag)
on realistic multi-component profiles, where dedup/reuse across components interact.
'''

import os
import types

import humon
import pytest

from configsys.app import Context
from configsys.routes import RouteResolver
from configsys.v2.engine import V2Resolver

from test_v2_fields import _signature  # reuse the per-family install signature

HERE = os.path.dirname(__file__)
ROUTES1 = os.path.join(HERE, '..', 'routes.hu')
ROUTES2 = os.path.join(HERE, '..', 'routes2.hu')
CONFIG = os.path.join(HERE, '..', 'config.hu')

CONTEXTS = [('ubuntu', '24.04'), ('ubuntu', '22.04'), ('pop_os!', '22.04'),
            ('debian', '12'), ('fedora', '41'), ('fedora', '42'),
            ('rhel', '9.8'), ('arch', '20260101')]


def _all_profile_components():
    trove = humon.from_file(CONFIG)
    root = trove.root
    names = set()
    for i in range(root.num_children):
        ch = root[i]
        if ch.key == 'configs' or not ch.key:
            continue
        if ch.kind == humon.NodeKind.LIST:
            for j in range(ch.num_children):
                v = ch[j].value
                if v:
                    names.add(v)
    return sorted(names)


COMPONENTS = _all_profile_components()


@pytest.mark.parametrize('block,version', CONTEXTS)
def test_profile_field_parity_across_os(block, version):
    old_r = RouteResolver(humon.from_file(ROUTES1), block, version)
    new_r = V2Resolver(ROUTES2, block, version, 'x86_64')

    for comp in COMPONENTS:
        try:
            old = old_r.resolve_names([comp])
        except Exception:
            continue                      # not routed here in old -> nothing to match
        new = new_r.resolve_names([comp])
        assert set(new) == set(old), (
            f'{comp} @ {block} {version}: unit keys differ\n'
            f'  old: {sorted(old)}\n  v2 : {sorted(new)}')
        for key in old:
            assert _signature(new[key], block) == _signature(old[key], block), (
                f'{comp} @ {block}: unit {key} install signature differs\n'
                f'  old fields: {old[key].fields}\n  v2  fields: {new[key].fields}')


def test_context_flag_selects_v2_resolver():
    env_args = types.SimpleNamespace(home=None, os='ubuntu', config=None, pretend=True)
    old_env = os.environ.get('CONFIGSYS_RESOLVER')
    try:
        os.environ['CONFIGSYS_RESOLVER'] = 'v2'
        ctx = Context(env_args)
        assert isinstance(ctx.routes, V2Resolver)
        os.environ.pop('CONFIGSYS_RESOLVER')
        ctx2 = Context(env_args)
        assert isinstance(ctx2.routes, RouteResolver)
    finally:
        if old_env is not None:
            os.environ['CONFIGSYS_RESOLVER'] = old_env
        else:
            os.environ.pop('CONFIGSYS_RESOLVER', None)
