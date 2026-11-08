'''tools/osaudit.py — the /update-os mechanics against a small synthetic routes file: registry
staleness, the per-release resolution delta, version-bounded bindings and release-pin gaps, the
release-dependent sources a new release must be probed for, and the sweep's refusal paths. (The
podman sweep and the network probes themselves are exercised by running the skill.)'''

import importlib.util
from pathlib import Path

import pytest

from configsys import routes

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('osaudit', HERE.parent / 'tools' / 'osaudit.py')
oa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oa)

ROUTES = '''{
  os: {
    linux: {}
    glibc_linux: { using: linux }
    redhat: { using: glibc_linux  native: dnf }
    fedora: { using: redhat  scale-root: true  releases: {
        43: { status: released  eol: 2026-12-02  image: "docker.io/library/fedora:43" }
        44: { status: released  image: "docker.io/library/fedora:44" }
        45: { status: prerelease  released: 2026-10-28  image: "docker.io/library/fedora:45" }
    } }
    debian: { using: glibc_linux  native: apt  scale-root: true }
    ubuntu: { using: debian  scale-root: true  releases: {
        22.04: { status: released  codename: jammy }
        24.04: { status: released  codename: noble  image: "docker.io/library/ubuntu:24.04" }
    } }
    zorin: { using: ubuntu  scale-root: true }
    fedora_atomic: { using: glibc_linux  native: brew  scale-root: true  releases: {
        44: { status: released  image: "ghcr.io/ublue-os/bazzite:stable" } } }
  }
  drivers: {}
  components: {
    folly:   { install: [ { via: native  when: "fedora < 44"  name: folly-devel } ] }
    jdk:     { install: [ { via: native  when: "not (fedora >= 44)"  name: java-21-openjdk-devel }
                          { via: native  when: "fedora >= 44"  name: java-25-openjdk-devel } ] }
    gcc-old: { install: [ { via: native  when: "fedora = 43"  name: gcc14 }
                          { via: native  when: "fedora = 44"  name: gcc15 } ] }
    headscale: { install: [ { via: native  when: "fedora >= 44" } ] }
    eol-only:  { install: [ { via: native  when: "fedora = 41"  name: old } ] }
    jellyfin: { install: [ { via: native  when: "fedora"
        repo-id: jellyfin  repo-url: "https://repo.example.org/fedora/$releasever/$basearch"
        pubkey-url: "https://repo.example.org/key-$releasever.asc" } ] }
    librewolf: { install: [ { via: native  when: "ubuntu"
        source-line: "deb [signed-by=/k.asc] https://deb.example.net $CODENAME main" } ] }
    perforce: { install: [ { via: native  when: "ubuntu"
        source-line: "deb [signed-by=/p.gpg] https://package.example.com/apt/ubuntu noble release" } ] }
    toolchain: { install: [ { via: native  when: "ubuntu"  ppa: ubuntu-toolchain-r/test  name: gcc-13 } ] }
  }
}'''


@pytest.fixture
def loaded(tmp_path, monkeypatch):
    path = tmp_path / 'routes.hu'
    path.write_text(ROUTES, encoding='utf-8')
    monkeypatch.setattr(oa, 'ROUTES', str(path))
    cascade, components, _m, _c = routes.load(str(path))
    return cascade, components


def test_lines_are_the_version_line_owners_with_their_tables_in_version_order(loaded):
    cascade, _ = loaded
    registry = oa.lines(cascade)
    assert list(registry['fedora']) == ['43', '44', '45']
    assert registry['zorin'] == {}                         # own numbering, no table yet
    assert 'linux' not in registry and 'redhat' not in registry
    assert oa.newest_live(registry['fedora']) == '44'
    assert oa.newest_live(registry['fedora'], include_prerelease=True) == '45'


def test_staleness_flags_what_the_calendar_overtook(loaded):
    cascade, _ = loaded
    kinds = {(f['line'], f.get('release'), f['kind']) for f in oa.staleness(cascade, '2026-12-10')}
    assert ('fedora', '43', 'eol-passed') in kinds
    assert ('fedora', '45', 'prerelease-past-ga') in kinds
    assert ('ubuntu', '22.04', 'no-image') in kinds
    assert ('zorin', None, 'no-registry') in kinds
    early = {f['kind'] for f in oa.staleness(cascade, '2026-01-01') if f['line'] == 'fedora'}
    assert early == set()


def test_delta_names_what_a_release_loses_gains_and_changes(loaded):
    d = oa.delta('fedora', '43', '44')
    assert set(d['lost']) == {'folly'}
    assert set(d['gained']) == {'headscale'}
    assert d['changed']['jdk'] == {'old': 'dnf:java-21-openjdk-devel',
                                   'new': 'dnf:java-25-openjdk-devel'}
    assert d['changed']['gcc-old'] == {'old': 'dnf:gcc14', 'new': 'dnf:gcc15'}


def test_pinned_reports_bounded_bindings_and_the_release_pin_gap(loaded):
    cascade, components = loaded
    found = {(f['component'], f['kind']): f for f in oa.pinned(cascade, components)}
    assert found[('folly', 'stops-short')]['covers'] == ['43']
    assert found[('jdk', 'stops-short')]['covers'] == ['43']      # an upper bound inside a `not`
    assert ('gcc-old', 'exact') in found or ('gcc-old', 'stops-short') in found
    gap = found[('gcc-old', 'release-pin-gap')]
    assert gap['newest'] == '45' and gap['covers'] == ['43', '44']
    assert found[('eol-only', 'no-live-release')]['covers'] == []
    assert ('headscale', 'from') not in found                    # plain lower bounds: --all only
    assert ('headscale', 'from') in {(f['component'], f['kind'])
                                     for f in oa.pinned(cascade, components, show_all=True)}


def test_release_dependent_sources_substitute_the_release(loaded):
    cascade, components = loaded
    fedora = {(c, k): u for c, k, u, _n in oa._release_sources(cascade, components, 'fedora', '45')}
    assert fedora[('jellyfin', 'repo-url')] == \
        'https://repo.example.org/fedora/45/x86_64/repodata/repomd.xml'
    assert fedora[('jellyfin', 'pubkey-url')] == 'https://repo.example.org/key-45.asc'

    ubuntu = oa._release_sources(cascade, components, 'ubuntu', '22.04')
    by = {(c, k): (u, n) for c, k, u, n in ubuntu}
    assert by[('librewolf', 'source-line')][0] == 'https://deb.example.net/dists/jammy/Release'
    assert 'noble' in by[('perforce', 'literal-codename')][1]
    assert by[('toolchain', 'ppa')][0] == \
        'https://ppa.launchpadcontent.net/ubuntu-toolchain-r/test/ubuntu/dists/jammy/Release'
    # on noble itself the literal codename is the right one
    noble = {(c, k) for c, k, _u, _n in oa._release_sources(cascade, components, 'ubuntu', '24.04')}
    assert ('perforce', 'literal-codename') not in noble


def test_sweep_refuses_lines_it_cannot_check(loaded):
    cascade, _ = loaded
    assert 'no container check' in oa.sweep(cascade, 'fedora_atomic')['error']   # brew: compaudit's
    assert 'no repo setup' in oa.sweep(cascade, 'zorin')['error']


def test_fixtures_reads_the_real_golden_contexts_and_containerfiles():
    cascade, _ = oa.load()
    found = oa.fixtures(cascade)
    assert any(f['fixture'] == 'test/Containerfile.fedora' for f in found)
