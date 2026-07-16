'''Equivalence harness: resolve the same components with the OLD RouteResolver and the
NEW v2 resolver across contexts, and assert the resolved unit matches. This is the gate
for porting a component — the diff must be empty before the new engine takes over.

The comparison is (family/mechanism, component, package-name) — the primary unit only
(dependency-closure equivalence arrives with the v2 worklist resolver).
'''

import os

import humon
import pytest

from configsys.routes import RouteResolver
from configsys.v2.resolve import resolve_one
from configsys.v2 import routes2

HERE = os.path.dirname(__file__)
ROUTES1 = os.path.join(HERE, '..', 'routes.hu')
ROUTES2 = os.path.join(HERE, '..', 'routes2.hu')

# (component, os-block, version, cpu)
CASES = [
    ('btop', 'ubuntu', '24.04', 'x86_64'),
    ('btop', 'pop_os!', '22.04', 'x86_64'),
    ('btop', 'fedora', '41', 'x86_64'),
    ('btop', 'arch', '20260101', 'x86_64'),
    ('libfuse2', 'ubuntu', '24.04', 'x86_64'),
    ('libfuse2', 'fedora', '41', 'x86_64'),
    ('libfuse2', 'arch', '20260101', 'x86_64'),
    ('libfuse2', 'pop_os!', '22.04', 'x86_64'),
    ('chrome', 'ubuntu', '24.04', 'x86_64'),
    ('chrome', 'fedora', '41', 'x86_64'),
    ('chrome', 'arch', '20260101', 'x86_64'),
    ('steam', 'pop_os!', '22.04', 'x86_64'),   # native path
    ('steam', 'ubuntu', '24.04', 'x86_64'),    # flatpak path
    ('steam', 'fedora', '41', 'x86_64'),
    ('steam', 'arch', '20260101', 'x86_64'),
]


def _old(component, block, version):
    r = RouteResolver(humon.from_file(ROUTES1), block, version)
    units = r.resolve_names([component])
    for rc in units.values():                 # the primary unit is the one for this comp
        if rc.comp == component:
            return (rc.family, rc.comp, rc.fields.get('name'))
    raise AssertionError(f'old resolver produced no primary unit for {component}')


def _new(component, block, version, cpu):
    cascade, components = routes2.load(ROUTES2)
    return resolve_one(component, cascade, components, block, version, cpu).as_tuple()


@pytest.mark.parametrize('comp,block,version,cpu', CASES)
def test_v2_matches_old(comp, block, version, cpu):
    assert _new(comp, block, version, cpu) == _old(comp, block, version)
