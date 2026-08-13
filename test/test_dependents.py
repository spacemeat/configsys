'''Resolver.dependents(name): the reverse-dependency query behind the Profiles screen's
"required by" line. Returns `(dependent, is_driver)` pairs — every component (and DRIVER) that
names a capability `name` provides in its requires/suggests/parts, at the component level OR any
binding, across all install methods (`when:`-gated ones included — the screen is machine-agnostic).'''

from configsys.routes import Resolver

OS = 'os: { linux: {}  debian: { using: linux  native: apt } }'
DRIVERS = 'drivers: { appimg: { requires: [ libfuse2 ] } }'   # a driver with an inherent require

COMPS = '''
    cmake:      { install: [ { via: native } ] }
    make:       { install: [ { via: native } ] }
    ripgrep:    { requires: [ cmake, make ]  install: [ { via: cargo } ] }
    lazygit:    { install: [ { via: source  requires: [ cmake ] } ] }
    yazi:       { suggests: [ cmake ]  install: [ { via: cargo } ] }
    bundle:     { parts: [ cmake ]  install: [ { via: parts } ] }
    kit:        { install: [ { via: parts  parts: [ cmake, make ] } ] }
    unrelated:  { install: [ { via: native } ] }
    libfuse2:   { install: [ { via: native } ] }
    viewer:     { requires: [ libfuse2 ]  install: [ { via: native } ] }
    python3.13: { provides: { python3: "3.13" }  install: [ { via: native } ] }
    tool:       { requires: { python3: ">=3.11" }  install: [ { via: pipx } ] }
'''


def _res(tmp_path, comps=COMPS, block='debian'):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  ' + DRIVERS + '  components: { ' + comps + ' } }')
    return Resolver(str(p), block, '12')


def test_dependents_gathers_component_and_binding_edges(tmp_path):
    r = _res(tmp_path)
    # cmake is required (component-level: ripgrep), required (binding-level: lazygit's source method),
    # suggested (yazi), a component-level part (bundle), AND a `via: parts` binding member (kit) —
    # every edge kind surfaces, sorted; all components (is_driver=False).
    assert r.dependents('cmake') == [('bundle', False), ('kit', False), ('lazygit', False),
                                     ('ripgrep', False), ('yazi', False)]


def test_dependents_matches_a_provided_capability_not_just_the_name(tmp_path):
    r = _res(tmp_path)
    # `tool` requires the python3 CAPABILITY (>=3.11); python3.13 provides it -> it's a dependent.
    assert r.dependents('python3.13') == [('tool', False)]


def test_dependents_includes_drivers_last_and_flagged(tmp_path):
    r = _res(tmp_path)
    # libfuse2 is required by the `viewer` component AND inherently by the `appimg` driver — the
    # component sorts first, the driver comes last flagged is_driver=True.
    assert r.dependents('libfuse2') == [('viewer', False), ('appimg', True)]


def test_dependents_empty_for_a_leaf_or_unknown(tmp_path):
    r = _res(tmp_path)
    assert r.dependents('ripgrep') == []        # nothing requires ripgrep (a leaf)
    assert r.dependents('nonexistent') == []
