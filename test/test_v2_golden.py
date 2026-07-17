'''Golden snapshot of v2 resolution — the regression gate that survives deleting v1.

The equivalence + field-parity harnesses proved v2 == the old RouteResolver. Once v1 is
gone those harnesses can't run, so we freeze the (then-proven-correct) v2 output here: for
every routes.hu component across every OS context, the full resolved closure as
{unit_key: {family, name, fields}} — exactly what the app hands the families. This guards
against future regressions in the resolver/data with no dependency on the old engine.

Regenerate after an intentional data/resolver change:
    CONFIGSYS_REGEN_GOLDEN=1 .venv/bin/python -m pytest test/test_v2_golden.py -q
and review the git diff of test/v2_golden.json before committing.
'''

import json
import os

import pytest

from configsys.v2 import routes2
from configsys.v2.engine import V2Resolver
from configsys.v2.resolve import ResolveError

HERE = os.path.dirname(__file__)
ROUTES2 = os.path.join(HERE, '..', 'routes2.hu')
GOLDEN = os.path.join(HERE, 'v2_golden.json')

CONTEXTS = [('ubuntu', '24.04'), ('ubuntu', '22.04'), ('pop_os!', '22.04'),
            ('debian', '12'), ('debian', '11'), ('fedora', '41'), ('fedora', '42'),
            ('rhel', '9.8'), ('arch', '20260101')]


def _canon(rc):
    return {'family': rc.family, 'name': rc.name, 'fields': rc.fields}


def _snapshot():
    _cascade, components, _mechs = routes2.load(ROUTES2)
    names = sorted(components)
    snap = {}
    for block, version in CONTEXTS:
        r = V2Resolver(ROUTES2, block, version, 'x86_64')
        ctx = {}
        for name in names:
            try:
                units = r.resolve_names([name])
            except ResolveError:
                continue                       # not routable here — nothing to snapshot
            ctx[name] = {k: _canon(rc) for k, rc in sorted(units.items())}
        snap[f'{block}@{version}'] = ctx
    return snap


def test_v2_resolution_matches_golden():
    snap = _snapshot()
    if os.environ.get('CONFIGSYS_REGEN_GOLDEN'):
        with open(GOLDEN, 'w', encoding='utf-8') as f:
            json.dump(snap, f, indent=1, sort_keys=True)
        pytest.skip('regenerated golden snapshot')
    with open(GOLDEN, encoding='utf-8') as f:
        golden = json.load(f)
    # compare context-by-context / component-by-component for readable failures
    assert set(snap) == set(golden), 'context set changed'
    for cxt in golden:
        assert set(snap[cxt]) == set(golden[cxt]), f'{cxt}: component set changed'
        for comp in golden[cxt]:
            assert snap[cxt][comp] == golden[cxt][comp], (
                f'{cxt} / {comp}: resolution changed\n'
                f'  golden: {golden[cxt][comp]}\n  now   : {snap[cxt][comp]}')
