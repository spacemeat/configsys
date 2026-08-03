'''The `version-floors:` section — a mergeable patch that tightens an existing requirement's floor
without redefining the component (stage 3b, the fold-in mechanism).'''

import os

from configsys.routes import Resolver

HERE = os.path.dirname(__file__)
ROUTES = os.path.join(HERE, '..', 'routes.hu')


def _plugin(tmp_path, body, name='vf.hu'):
    p = tmp_path / name
    p.write_text(body, encoding='utf-8')
    return (str(p), 'plugin')


_SRC = '{ components: { ripgrep: { install: [ { via: source  repo: "https://x/y"  requires: cargo  build: "x" } ] } }'


def _src_binding(r):
    return next(b for b in r.components['ripgrep'].bindings if b.via == 'source')


def test_floor_folds_onto_the_requiring_binding(tmp_path):
    body = _SRC + '  version-floors: { ripgrep: { cargo: ">=1.96" } } }'
    r = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', plugin_files=[_plugin(tmp_path, body)])
    assert _src_binding(r).req_versions == {'cargo': '>=1.96'}


def test_floor_ignored_when_cap_not_required(tmp_path):
    # core ripgrep is native only (requires no cargo) -> a cargo floor tightens nothing
    body = '{ version-floors: { ripgrep: { cargo: ">=1.96" } } }'
    r = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', plugin_files=[_plugin(tmp_path, body)])
    comp = r.components['ripgrep']
    assert 'cargo' not in comp.req_versions
    assert all('cargo' not in b.req_versions for b in comp.bindings)


def test_later_layer_wins(tmp_path):
    low = _plugin(tmp_path, _SRC + '  version-floors: { ripgrep: { cargo: ">=1.90" } } }', 'low.hu')
    hi = _plugin(tmp_path, '{ version-floors: { ripgrep: { cargo: ">=1.96" } } }', 'hi.hu')
    r = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', plugin_files=[low, hi])
    assert _src_binding(r).req_versions['cargo'] == '>=1.96'      # higher layer wins per (comp, cap)


def test_resolution_is_unchanged_by_a_floor(tmp_path):
    # the floor adds only version metadata — the resolved unit set must be identical
    plain = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', pins={'ripgrep': 'source'},
                     plugin_files=[_plugin(tmp_path, _SRC + ' }', 'plain.hu')])
    floored = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', pins={'ripgrep': 'source'},
                       plugin_files=[_plugin(tmp_path, _SRC + '  version-floors: { ripgrep: { cargo: ">=1.96" } } }', 'f.hu')])
    assert set(plain.resolve_names(['ripgrep'])) == set(floored.resolve_names(['ripgrep']))
