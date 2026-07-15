import humon
import pytest

from configsys.errors import ConfigError
from configsys.routes import RouteResolver

# A minimal routes trove exercising version variants + the cascade.
ROUTES = '''{
    \\apt: {
        pipx: { name: pipx }
        foo:  { name: foo }
    }
    \\pip: { pipx: { name: pipx } }

    linux: {}
    debian: { !using: linux  *: apt\\*  foo: apt\\foo }
    ubuntu: { !using: debian }
    pop_os!: { !using: ubuntu }

    "ubuntu@<23.04": { pipx: pip\\pipx }
    "debian@<12":    { pipx: pip\\pipx }
}'''


def resolve(block, version, name):
    tr = humon.from_string(ROUTES)
    r = RouteResolver(tr, block, version)
    units, _ = r.resolve_with_roots([name])
    return r, sorted(units)


def test_variant_layered_ahead_of_base():
    r, _ = resolve('ubuntu', '22.04', 'foo')
    assert r.cascade_names == ['ubuntu@<23.04', 'ubuntu', 'debian', 'linux']


def test_no_variant_on_modern():
    r, _ = resolve('ubuntu', '24.04', 'foo')
    assert r.cascade_names == ['ubuntu', 'debian', 'linux']


def test_pipx_routes_to_pip_bootstrap_on_old_ubuntu():
    _, units = resolve('ubuntu', '22.04', 'pipx')
    assert 'pip\\pipx' in units and 'apt\\pipx' not in units


def test_pipx_routes_to_apt_on_modern():
    _, units = resolve('ubuntu', '24.04', 'pipx')
    assert 'apt\\pipx' in units and 'pip\\pipx' not in units


def test_variant_flows_through_inheritance_to_pop_os():
    # Pop!_OS -> ubuntu; the ubuntu@<23.04 variant applies with no pop-specific block.
    r, units = resolve('pop_os!', '22.04', 'pipx')
    assert r.cascade_names == ['pop_os!', 'ubuntu@<23.04', 'ubuntu', 'debian', 'linux']
    assert 'pip\\pipx' in units


def test_debian_variant_does_not_fire_on_ubuntu_version():
    # ubuntu 22.04 must not pick up "debian@<12" (numbering safety of the pattern).
    r, _ = resolve('ubuntu', '22.04', 'foo')
    assert 'debian@<12' not in r.cascade_names


def test_no_version_means_base_only():
    r, _ = resolve('ubuntu', None, 'foo')
    assert r.cascade_names == ['ubuntu', 'debian', 'linux']


def test_ambiguous_variants_raise():
    routes = '''{
        \\apt: { pipx: { name: pipx } }
        \\pip: { pipx: { name: pipx } }
        linux: {}
        debian: { !using: linux  *: apt\\* }
        ubuntu: { !using: debian }
        "ubuntu@<23.04":  { pipx: pip\\pipx }
        "ubuntu@>=20.04": { pipx: pip\\pipx }
    }'''
    tr = humon.from_string(routes)
    with pytest.raises(ConfigError):
        RouteResolver(tr, 'ubuntu', '22.04')   # both single-comparator -> same specificity
