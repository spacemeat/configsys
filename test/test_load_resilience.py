'''review-2026-11-2 B4: bad data never bricks load — a parts cycle is an error row and a `check`
error, a broken plugin definition (via-less binding, pathological when:, an ambiguity it causes in a
component you also amend, a file it includes) is skipped with a warning, and a malformed version
constraint abstains (never met) instead of a TypeError.'''

import pytest

from configsys import routecheck, routes
from configsys.routes import Resolver

OS = 'os: { linux: {}  debian: { using: linux  native: apt  scale-root: true } }'


def _routes(tmp_path, comps):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  components: { ' + comps + ' } }')
    return str(p)


def _plugin(tmp_path, text, extra=None):
    d = tmp_path / 'plugins' / 'plug'
    d.mkdir(parents=True)
    (d / 'plugin.hu').write_text('{ name: plug  requires-abi: 1 }')
    (d / 'plug.hu').write_text(text)
    for name, body in (extra or {}).items():
        (d / name).write_text(body)
    return str(d / 'plug.hu')


def test_a_parts_cycle_is_an_error_row_not_a_crash(tmp_path):
    r = Resolver(_routes(tmp_path, 'a: { parts: [ b ] }  b: { parts: [ a ] }  c: { install: [ { via: native } ] }'),
                 'debian', '12')
    units, errs = r.resolve_resilient(['a', 'c'])
    assert 'parts cycle' in errs['a'] and 'apt\\c' in units
    issues = routecheck.validate(r.components, r.cascade, r.drivers)
    assert any(i.kind == 'parts-cycle' for i in issues)


@pytest.mark.parametrize('bad', [
    '{ components: { x: { install: [ { name: nope } ] } } }',                        # no via:
    '{ components: { x: { install: [ { via: native  when: "' + '(' * 3000 + 'debian' + ')' * 3000 + '" } ] } } }',
])
def test_a_broken_plugin_definition_is_skipped(tmp_path, bad):
    warns = []
    routes.load(_routes(tmp_path, 'ok: { install: [ { via: native } ] }'),
                plugin_files=[_plugin(tmp_path, bad)], warnings_out=warns)
    assert any('skipped' in w or 'x' in w for w in warns)


def test_a_plugins_include_is_forgiven_like_the_plugin(tmp_path):
    bad = '{ components: { broken: { install: [ { via: native  when: "debian" } { via: native  when: "cpu: x86_64" } ] } } }'
    warns = []
    routes.load(_routes(tmp_path, 'ok: { install: [ { via: native } ] }'),
                plugin_files=[_plugin(tmp_path, '{ include: [ sub.hu ] }', {'sub.hu': bad})],
                warnings_out=warns)
    assert any('broken' in w for w in warns)


def test_a_plugin_making_your_amended_component_ambiguous_is_dropped_not_fatal(tmp_path):
    comps = 'tool: { install: [ { via: native } ] }'
    plug = _plugin(tmp_path, '{ components: { tool: { install: [ { via: native  when: "debian" }  { via: native  when: "cpu: x86_64" } ] } } }')
    user = tmp_path / 'user.hu'
    user.write_text('{ components: { tool: { description: "mine" } } }')
    warns = []
    _c, components, _d, _o = routes.load(_routes(tmp_path, comps), overrides_path=str(user),
                                         plugin_files=[plug], warnings_out=warns)
    assert components['tool'].description == 'mine'
    assert any('ignored the plugin layer' in w for w in warns)


def test_a_malformed_constraint_abstains_and_check_says_so(tmp_path):
    from configsys.versionsweep import meets
    assert meets('3.12', '>=v3.11')                         # a leading v is read as 3.11
    assert meets('3.12', '>=abc') is False                  # unreadable: never met, no TypeError
    r = Resolver(_routes(tmp_path, 'py: { provides: { python3: 3.12 }  install: [ { via: native } ] }'
                         '  foo: { requires: [ { python3: ">=abc" } ]  install: [ { via: native } ] }'),
                 'debian', '12')
    r.resolve_resilient(['foo'])                             # no crash
    issues = routecheck.validate(r.components, r.cascade, r.drivers)
    assert any(i.kind == 'bad-constraint' for i in issues)


def test_a_pick_sharing_a_failing_dependency_gets_its_own_error_row(tmp_path):
    # B5 (routing-02): the second pick used to vanish — no unit, no error
    r = Resolver(_routes(tmp_path, 'libc: { requires: nothing-provides-this  install: [ { via: native } ] }'
                         '  a: { requires: libc  install: [ { via: native } ] }'
                         '  b: { requires: libc  install: [ { via: native } ] }'), 'debian', '12')
    units, errs = r.resolve_resilient(['a', 'b'])
    assert units == {} and set(errs) == {'a', 'b'}
    assert 'nothing-provides-this' in errs['b']
