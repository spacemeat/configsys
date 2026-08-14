'''Version-scoped JDK providers — the python3.X pattern for Java. `jdk` is the default (OpenJDK 21,
provides { jdk: 21 }); jdk-17/jdk-25 are never-auto siblings; a `requires: { jdk: ">=N" }` selects
the matching line, a plain `requires: jdk` takes the default with no ambiguity.'''

from configsys.routes import Resolver


def _jdks(units):
    return sorted(k.split('\\')[1] for k in units if k.split('\\')[1].startswith('jdk'))


def _scratch(tmp_path):
    p = tmp_path / 'routes.hu'
    p.write_text('''{ os: { linux: {}  debian: { using: linux  native: apt } }
      components: {
        jdk:    { provides: { jdk: 21 }  install: [ { via: native } ] }
        jdk-17: { standing: never-auto  provides: { jdk: 17 }  install: [ { via: native } ] }
        jdk-25: { standing: never-auto  provides: { jdk: 25 }  install: [ { via: native } ] }
        anyjdk: { requires: jdk                 install: [ { via: native } ] }
        j21:    { requires: { jdk: ">=21" }      install: [ { via: native } ] }
        j25:    { requires: { jdk: ">=25" }      install: [ { via: native } ] }
        jold:   { requires: { jdk: "<21" }       install: [ { via: native } ] }
      } }''')
    return Resolver(str(p), 'debian', '12')


def test_unversioned_requires_takes_the_default_no_ambiguity(tmp_path):
    r = _scratch(tmp_path)
    u, e = r.resolve_resilient(['anyjdk'])
    assert not e.get('anyjdk')          # jdk-17/25 are never-auto -> jdk is the sole ordinary provider
    assert _jdks(u) == ['jdk']


def test_version_constraint_selects_the_matching_line(tmp_path):
    r = _scratch(tmp_path)
    assert _jdks(r.resolve_resilient(['j21'])[0]) == ['jdk']       # 21 default meets >=21
    assert _jdks(r.resolve_resilient(['j25'])[0]) == ['jdk-25']    # only 25 meets >=25 (constraint enables it)
    assert _jdks(r.resolve_resilient(['jold'])[0]) == ['jdk-17']   # only 17 meets <21


def test_real_routes_jdk_family_shape():
    r = Resolver('routes.hu', 'ubuntu', '24.04')
    # the default `jdk` provides jdk:21; the siblings are never-auto opt-ins
    assert r.components['jdk'].prov_versions.get('jdk') == '21'
    for sib in ('jdk-17', 'jdk-25', 'graalvm'):
        assert r.components[sib].opt_in, f'{sib} should be never-auto'
    # a plain `requires: jdk` consumer (scala) resolves the default with no ambiguity
    u, e = r.resolve_resilient(['scala'])
    assert not e.get('scala') and 'jdk' in {k.split('\\')[1] for k in u}
