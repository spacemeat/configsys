'''A unit's `soft_deps`: the keys it pulled in ONLY through `suggests:` (planning orders them after
it, never first). Checked on the real catalog, where docker-compose suggests the standalone link
that hard-requires it.'''

import os

from configsys.routes import Resolver

ROUTES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'routes.hu')


def test_suggests_edges_are_soft_and_requires_edges_hard():
    r = Resolver(ROUTES, 'pop_os!', '22.04', 'x86_64', command_trust=lambda _p: True)
    units, errors = r.resolve_resilient(['docker-compose'])
    assert not errors
    compose, link = units['apt\\docker-compose'], units['script\\docker-compose-standalone']
    assert link.key in compose.deps and compose.soft_deps == {link.key}
    assert compose.key in link.deps and link.soft_deps == set()
