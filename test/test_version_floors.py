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


def test_resolve_resilient_extra_pins_without_mutating_resolver(tmp_path):
    # auto-tighten re-resolves with extra pins layered on, leaving the Resolver's own pins intact
    r = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', plugin_files=[_plugin(tmp_path, _SRC + ' }')])
    default = r.resolve_resilient(['ripgrep'])[0]
    pinned = r.resolve_resilient(['ripgrep'], extra_pins={'ripgrep': 'source'})[0]
    assert any(k.startswith('source\\') for k in pinned)          # extra pin took effect
    assert not any(k.startswith('source\\') for k in default)     # default was native
    assert r.pins == {}                                           # resolver not mutated


def test_resolution_is_unchanged_by_a_floor(tmp_path):
    # the floor adds only version metadata — the resolved unit set must be identical
    plain = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', pins={'ripgrep': 'source'},
                     plugin_files=[_plugin(tmp_path, _SRC + ' }', 'plain.hu')])
    floored = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', pins={'ripgrep': 'source'},
                       plugin_files=[_plugin(tmp_path, _SRC + '  version-floors: { ripgrep: { cargo: ">=1.96" } } }', 'f.hu')])
    assert set(plain.resolve_names(['ripgrep'])) == set(floored.resolve_names(['ripgrep']))


# -- layer precedence: a patch SETS an existing floor unless the `requires:` that wrote that floor
#    sits in a HIGHER layer than the patch; a bare requirement has no floor to defend ------------

_SRC_FLOORED = ('{ components: { ripgrep: { install: [ { via: source  repo: "https://x/y"  '
                'requires: [ { cargo: ">=1.96" } ]  build: "x" } ] } }')
_COMP_FLOORED = ('{ components: { ripgrep: { requires: [ { cargo: ">=1.96" } ]  install: [ '
                 '{ via: source  repo: "https://x/y"  build: "x" } ] } }')


def _floors(con):
    return '{ version-floors: { ripgrep: { cargo: "' + con + '" } } }'


def test_a_higher_layer_floor_loosens_an_inline_one(tmp_path):
    # the user manages: a patch above the definition replaces its floor, looser included
    lo = _plugin(tmp_path, _SRC_FLOORED + ' }', 'lo.hu')
    hi = _plugin(tmp_path, _floors('>=1.80'), 'hi.hu')
    r = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', plugin_files=[lo, hi])
    assert _src_binding(r).req_versions == {'cargo': '>=1.80'}


def test_a_higher_layer_floor_tightens_an_inline_one(tmp_path):
    lo = _plugin(tmp_path, _SRC_FLOORED + ' }', 'lo.hu')
    hi = _plugin(tmp_path, _floors('>=1.99'), 'hi.hu')
    r = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', plugin_files=[lo, hi])
    assert _src_binding(r).req_versions == {'cargo': '>=1.99'}


def test_a_higher_layer_floor_replaces_an_incomparable_one(tmp_path):
    # replaced, not combined: `<2` from above stands alone
    lo = _plugin(tmp_path, _SRC_FLOORED + ' }', 'lo.hu')
    hi = _plugin(tmp_path, _floors('<2'), 'hi.hu')
    r = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', plugin_files=[lo, hi])
    assert _src_binding(r).req_versions == {'cargo': '<2'}


def test_a_lower_layer_floor_never_overrides_a_higher_definition(tmp_path):
    lo = _plugin(tmp_path, _floors('>=1.80'), 'lo.hu')
    hi = _plugin(tmp_path, _SRC_FLOORED + ' }', 'hi.hu')
    r = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', plugin_files=[lo, hi])
    assert _src_binding(r).req_versions == {'cargo': '>=1.96'}         # looser: kept out
    lo2 = _plugin(tmp_path, _floors('>=1.99'), 'lo2.hu')
    r = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', plugin_files=[lo2, hi])
    assert _src_binding(r).req_versions == {'cargo': '>=1.96'}         # stricter: kept out too


def test_a_lower_layer_floor_fills_a_bare_requirement(tmp_path):
    # a bare `requires: cargo` sets no floor, so any layer's patch supplies it — a floors data
    # plugin sorted below the recipes it serves (configsys-versions under configsys-source)
    lo = _plugin(tmp_path, _floors('>=1.90'), 'lo.hu')
    hi = _plugin(tmp_path, _SRC + ' }', 'hi.hu')
    r = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', plugin_files=[lo, hi])
    assert _src_binding(r).req_versions == {'cargo': '>=1.90'}


def test_a_same_layer_floor_sets_the_inline_one(tmp_path):
    # not from a LOWER layer, so the file's own patch is its last word on that floor
    body = _SRC_FLOORED + '  version-floors: { ripgrep: { cargo: ">=1.80" } } }'
    r = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', plugin_files=[_plugin(tmp_path, body)])
    assert _src_binding(r).req_versions == {'cargo': '>=1.80'}


def test_the_binding_layer_counts_not_a_later_amend(tmp_path):
    # a higher layer that only ADDS a binding doesn't re-author the source binding's requires:
    # a patch between the two still sets the source binding's floor
    lo = _plugin(tmp_path, _SRC_FLOORED + ' }', 'lo.hu')
    mid = _plugin(tmp_path, _floors('>=1.80'), 'mid.hu')
    hi = _plugin(tmp_path, '{ components: { ripgrep: { install: [ { via: cargo } ] } } }', 'hi.hu')
    r = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', plugin_files=[lo, mid, hi])
    assert _src_binding(r).req_versions == {'cargo': '>=1.80'}


def test_component_level_requires_follow_the_same_rule(tmp_path):
    comp_def = _plugin(tmp_path, _COMP_FLOORED + ' }', 'def.hu')
    below = _plugin(tmp_path, _floors('>=1.80'), 'below.hu')
    above = _plugin(tmp_path, _floors('>=1.70'), 'above.hu')
    r = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', plugin_files=[below, comp_def])
    assert r.components['ripgrep'].req_versions == {'cargo': '>=1.96'}
    r = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', plugin_files=[comp_def, above])
    assert r.components['ripgrep'].req_versions == {'cargo': '>=1.70'}


def test_check_has_no_loose_floor_warning(tmp_path):
    # the retired "version-floors only tighten" rule: a looser patch is honored, nothing to warn
    from configsys import routecheck
    lo = _plugin(tmp_path, _SRC_FLOORED + ' }', 'lo.hu')
    hi = _plugin(tmp_path, _floors('>=1.80'), 'hi.hu')
    r = Resolver(ROUTES, 'ubuntu', '24.04', 'x86_64', plugin_files=[lo, hi])
    issues = routecheck.validate({'ripgrep': r.components['ripgrep']}, r.cascade, r.drivers,
                                 components_checked=True)
    assert not [i for i in issues if i.kind == 'loose-floor']
    assert not hasattr(r.components['ripgrep'], 'loose_floors')
