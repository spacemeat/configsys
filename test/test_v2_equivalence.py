'''Equivalence harness: resolve the same components with the OLD RouteResolver and the
NEW v2 resolver across contexts, and assert they match. This is the gate for porting a
component — the diff must be empty before the new engine takes over.

Two levels:
  * primary unit   — (mechanism, component, package) of the requested component
  * full closure   — the whole set of resolved unit keys (deps included), plus
                     requested_as attribution for reuse.
'''

import os

import humon
import pytest

from configsys.routes import RouteResolver
from configsys.v2 import routes2
from configsys.v2.resolve import resolve, resolve_one

HERE = os.path.dirname(__file__)
ROUTES1 = os.path.join(HERE, '..', 'routes.hu')
ROUTES2 = os.path.join(HERE, '..', 'routes2.hu')


def _old(block, version):
    return RouteResolver(humon.from_file(ROUTES1), block, version)


def _v2():
    return routes2.load(ROUTES2)


# -- primary-unit equivalence ---------------------------------------------

PRIMARY = [
    ('btop', 'ubuntu', '24.04'), ('btop', 'fedora', '41'), ('btop', 'arch', '20260101'),
    ('libfuse2', 'fedora', '41'), ('libfuse2', 'arch', '20260101'),
    ('chrome', 'ubuntu', '24.04'),
    ('steam', 'pop_os!', '22.04'), ('steam', 'ubuntu', '24.04'),
]


@pytest.mark.parametrize('comp,block,version', PRIMARY)
def test_primary_unit_matches(comp, block, version):
    units = _old(block, version).resolve_names([comp])
    old = next((rc.family, rc.comp, rc.fields.get('name'))
               for rc in units.values() if rc.comp == comp)
    cascade, components, _ = _v2()
    new = resolve_one(comp, cascade, components, block, version, 'x86_64').as_tuple()
    assert new == old


# -- full-closure equivalence ---------------------------------------------

CLOSURE = [
    ('btop', 'ubuntu', '24.04'),
    ('chrome', 'ubuntu', '24.04'), ('chrome', 'fedora', '41'), ('chrome', 'arch', '20260101'),
    ('tree-sitter-cli', 'ubuntu', '24.04'), ('tree-sitter-cli', 'arch', '20260101'),
    ('mononoki-nerd', 'ubuntu', '24.04'), ('mononoki-nerd', 'fedora', '41'),
    ('steam', 'pop_os!', '22.04'),          # native, no deps
    ('steam', 'ubuntu', '24.04'),           # flatpak -> pulls the flatpak tool
    ('libfuse2', 'arch', '20260101'),
]


@pytest.mark.parametrize('comp,block,version', CLOSURE)
def test_closure_matches(comp, block, version):
    old = set(_old(block, version).resolve_names([comp]))
    cascade, components, mechanisms = _v2()
    new = set(resolve([comp], cascade, components, mechanisms, block, version, 'x86_64'))
    assert new == old


# -- reuse + attribution --------------------------------------------------

def test_reuse_and_requested_as():
    # chrome and steam both go flatpak on Ubuntu; the flatpak tool resolves ONCE and is
    # attributed to both roots.
    old = _old('ubuntu', '24.04').resolve_names(['chrome', 'steam'])
    cascade, components, mechanisms = _v2()
    new = resolve(['chrome', 'steam'], cascade, components, mechanisms, 'ubuntu', '24.04', 'x86_64')

    assert set(new) == set(old)
    assert new['apt\\flatpak'].requested_as == {'chrome', 'steam'}
    assert new['apt\\flatpak'].requested_as == old['apt\\flatpak'].requested_as
