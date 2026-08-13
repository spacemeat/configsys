'''Resolver.dependents(name): the reverse-dependency query behind the Profiles screen's
"required by" line. Every component that names a capability `name` provides in its own
requires/suggests/parts — at the component level OR in ANY binding, across all install methods
(`when:`-gated ones included, since the Profiles screen is machine-agnostic).'''

from configsys.routes import Resolver

OS = 'os: { linux: {}  debian: { using: linux  native: apt } }'

COMPS = '''
    cmake:      { install: [ { via: native } ] }
    make:       { install: [ { via: native } ] }
    ripgrep:    { requires: [ cmake, make ]  install: [ { via: cargo } ] }
    lazygit:    { install: [ { via: source  requires: [ cmake ] } ] }
    yazi:       { suggests: [ cmake ]  install: [ { via: cargo } ] }
    bundle:     { parts: [ cmake ]  install: [ { via: parts } ] }
    kit:        { install: [ { via: parts  parts: [ cmake, make ] } ] }
    unrelated:  { install: [ { via: native } ] }
    python3.13: { provides: { python3: "3.13" }  install: [ { via: native } ] }
    tool:       { requires: { python3: ">=3.11" }  install: [ { via: pipx } ] }
'''


def _res(tmp_path, comps=COMPS, block='debian'):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  components: { ' + comps + ' } }')
    return Resolver(str(p), block, '12')


def test_dependents_gathers_component_and_binding_edges(tmp_path):
    r = _res(tmp_path)
    # cmake is required (component-level: ripgrep), required (binding-level: lazygit's source method),
    # suggested (yazi), a component-level part (bundle), AND a `via: parts` binding member (kit) —
    # every edge kind surfaces, sorted.
    assert r.dependents('cmake') == ['bundle', 'kit', 'lazygit', 'ripgrep', 'yazi']


def test_dependents_matches_a_provided_capability_not_just_the_name(tmp_path):
    r = _res(tmp_path)
    # `tool` requires the python3 CAPABILITY (>=3.11); python3.13 provides it -> it's a dependent.
    assert r.dependents('python3.13') == ['tool']


def test_dependents_empty_for_a_leaf_or_unknown(tmp_path):
    r = _res(tmp_path)
    assert r.dependents('ripgrep') == []        # nothing requires ripgrep (a leaf)
    assert r.dependents('nonexistent') == []
