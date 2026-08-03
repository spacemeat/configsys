'''Unit tests for floorderive — auto-deriving version floors from build manifests. Pure (fetch is
injected), so no network.'''

from configsys import floorderive as fd
from configsys.routes import Component


def test_rust_msrv_extractor():
    assert fd._rust_msrv('[package]\nname = "rg"\nrust-version = "1.96"\nedition = "2021"\n') == '1.96'
    assert fd._rust_msrv("rust-version = '1.88.0'") == '1.88.0'
    assert fd._rust_msrv('[package]\nname = "x"\n') is None            # no MSRV declared


def test_go_directive_extractor():
    assert fd._go_directive('module x\n\ngo 1.25\n') == '1.25'
    assert fd._go_directive('module x\ngo 1.26.0\nrequire ()\n') == '1.26.0'
    assert fd._go_directive('module x\n') is None
    # a `require ( go ... )` line must not be mistaken for the top-level go directive
    assert fd._go_directive('module x\n\ngo 1.25\n\nrequire (\n\tfoo v1\n)\n') == '1.25'


def test_raw_url_forms():
    u = fd._raw_url('https://github.com/BurntSushi/ripgrep', 'Cargo.toml')
    assert u == 'https://raw.githubusercontent.com/BurntSushi/ripgrep/HEAD/Cargo.toml'
    assert fd._raw_url('https://github.com/a/b.git', 'go.mod', ref='v1.2.3') == \
        'https://raw.githubusercontent.com/a/b/v1.2.3/go.mod'


def _src(repo, cap):
    return Component('c', {'install': [{'via': 'source', 'repo': repo, 'requires': cap}]})


def test_derive_floors_maps_cap_to_manifest():
    comps = {
        'ripgrep': _src('https://github.com/BurntSushi/ripgrep', 'cargo'),
        'lazygit': _src('https://github.com/jesseduffield/lazygit', 'go'),
    }

    def fetch(url):
        return 'rust-version = "1.96"' if url.endswith('Cargo.toml') else 'go 1.25'

    assert fd.derive_floors(comps, fetch) == {'ripgrep': {'cargo': '>=1.96'},
                                              'lazygit': {'go': '>=1.25'}}


def test_built_ref_prefers_explicit_ref_then_tag_then_head():
    from configsys.routes import Binding
    assert fd.built_ref(Binding({'via': 'source', 'ref': '9.0.0'})) == '9.0.0'
    # no ref, no version spec -> HEAD
    assert fd.built_ref(Binding({'via': 'source'})) == 'HEAD'


def test_derive_reads_the_built_tag_not_head():
    # the floor must come from the version the binding BUILDS (its tag), not HEAD
    comps = {'lazygit': Component('lazygit', {'install': [{
        'via': 'source', 'repo': 'https://github.com/jesseduffield/lazygit',
        'requires': 'go', 'version': {'github': 'jesseduffield/lazygit'}, 'tag-prefix': 'v'}]})}
    seen = {}

    def fetch(url):
        seen['url'] = url
        return 'go 1.25'

    fd.derive_floors(comps, fetch, ref_of=lambda b: 'v0.63.1')   # the resolved built tag
    assert '/v0.63.1/go.mod' in seen['url']                      # fetched the TAG, not HEAD


def test_derive_skips_non_source_and_non_derivable():
    comps = {
        # a native binding (no repo) -> nothing to derive
        'btop-native': Component('btop-native', {'install': [{'via': 'native'}]}),
        # a source recipe requiring a cap we can't derive (cc) -> skipped
        'htop': _src('https://github.com/htop-dev/htop', 'cc'),
    }
    assert fd.derive_floors(comps, lambda url: 'anything') == {}


def test_derive_tolerates_fetch_failure():
    comps = {'x': _src('https://github.com/a/b', 'cargo')}

    def boom(url):
        raise OSError('network down')

    assert fd.derive_floors(comps, boom) == {}          # a fetch failure just yields no floor


def test_emit_floors_is_a_version_floors_block():
    out = fd.emit_floors({'ripgrep': {'cargo': '>=1.96'}})
    assert 'version-floors' in out and 'ripgrep' in out and '>=1.96' in out
