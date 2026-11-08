'''The OS release registry (`releases:` on the block that owns a version line) — which block's table
a machine reads (OsCascade.version_line / releases), and `check`'s lint of a malformed table
(routecheck.release_registry_issues). docs/routing-model.md §6; docs/todo/os-releases-plan.md.'''

from configsys import routecheck
from configsys.routes import OsCascade

FEDORA_RELEASES = {
    '43': {'status': 'released', 'released': '2025-10-28', 'image': 'fedora:43'},
    '44': {'status': 'released', 'image': 'fedora:44'},
    '45': {'status': 'prerelease', 'image': 'fedora:45'},
}


def _cascade(**extra):
    blocks = {
        'linux': {},
        'glibc_linux': {'using': 'linux'},
        'redhat': {'using': 'glibc_linux', 'native': 'dnf'},
        'fedora': {'using': 'redhat', 'scale-root': 'true', 'releases': FEDORA_RELEASES},
        'nobara': {'using': 'fedora'},
        'debian': {'using': 'glibc_linux', 'native': 'apt', 'scale-root': 'true'},
        'ubuntu': {'using': 'debian', 'scale-root': 'true'},
        'linuxmint': {'using': 'ubuntu', 'scale-root': 'true'},
        'alpine': {'using': 'linux', 'native': 'apk',
                   'releases': {'3.24': {'status': 'released', 'image': 'alpine:3.24'}}},
        'arch': {'using': 'glibc_linux', 'native': 'pacman'},
    }
    blocks.update(extra)
    return OsCascade(blocks)


def test_a_derivative_without_its_own_scale_reads_its_parents_table():
    c = _cascade()
    assert c.version_line('nobara') == 'fedora'
    assert set(c.releases('nobara')) == {'43', '44', '45'}


def test_an_own_numbering_derivative_never_falls_through_to_the_parents_table():
    c = _cascade()
    assert c.version_line('linuxmint') == 'linuxmint'
    assert c.releases('linuxmint') == {}            # Mint 22 is not Ubuntu 22.x


def test_a_line_with_no_scale_root_above_it_is_owned_by_the_block_declaring_releases():
    c = _cascade()
    assert c.version_line('alpine') == 'alpine'
    assert set(c.releases('alpine')) == {'3.24'}


def test_a_rolling_block_has_no_line_and_no_table():
    c = _cascade()
    assert c.version_line('arch') is None and c.releases('arch') == {}


def test_a_well_formed_registry_lints_clean():
    assert routecheck.release_registry_issues(_cascade()) == []


def test_lint_reports_each_malformed_entry():
    c = _cascade(
        nobara={'using': 'fedora', 'releases': {'42': {'status': 'released'}}},
        ubuntu={'using': 'debian', 'scale-root': 'true', 'releases': {
            'noble': {'status': 'released'},
            '24.04': {'status': 'supported', 'eol': '2029/04', 'kernel': '6.8'},
            '26.04': 'released',
        }},
    )
    messages = [m for m, _src in routecheck.release_registry_issues(c)]
    text = '\n'.join(messages)
    assert "'nobara' reads its versions on the 'fedora' line" in text
    assert 'noble: not a version' in text
    assert "24.04: status 'supported'" in text
    assert "24.04: unknown field 'kernel'" in text
    assert "24.04: eol: '2029/04' is not YYYY-MM-DD" in text
    assert '26.04: must be a map' in text


def test_check_surfaces_registry_lint_as_os_release_warnings():
    c = _cascade(ubuntu={'using': 'debian', 'scale-root': 'true',
                         'releases': {'24.04': {'status': 'gone'}}})
    issues = routecheck.validate({}, c, {})
    kinds = [(i.kind, i.severity) for i in issues]
    assert ('os-release', 'warning') in kinds
