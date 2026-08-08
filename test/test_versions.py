import json

from configsys import versions
from configsys.paths import Paths


def fetcher(responses):
    calls = []

    def fetch(url, timeout=10):
        calls.append(url)
        return responses[url]

    fetch.calls = calls
    return fetch


GH = 'https://api.github.com/repos/neovim/neovim/releases/latest'


def test_static_never_fetches():
    f = fetcher({})
    assert versions.discover({'static': '1.2.3'}, fetch=f) == '1.2.3'
    assert f.calls == []


def test_github_tag():
    f = fetcher({GH: json.dumps({'tag_name': 'v0.10.2'})})
    assert versions.discover({'github': 'neovim/neovim'}, fetch=f) == 'v0.10.2'


def test_github_strip_v():
    f = fetcher({GH: json.dumps({'tag_name': 'v0.10.2'})})
    assert versions.discover({'github': 'neovim/neovim', 'strip-v': True}, fetch=f) == '0.10.2'


def test_url_regex_extract():
    f = fetcher({'https://x/latest.txt': '  version 1.4.350.1 released\n'})
    assert versions.discover({'url': 'https://x/latest.txt'}, fetch=f) == '1.4.350.1'


RELEASE_JSON = json.dumps({
    'tag_name': 'v0.12.4',
    'assets': [
        {'name': 'nvim-linux-arm64.appimage',
         'browser_download_url': 'https://gh/arm64.appimage'},
        {'name': 'nvim-linux-x86_64.appimage',
         'browser_download_url': 'https://gh/x86_64.appimage'},
        {'name': 'nvim-linux-x86_64.appimage.zsync',
         'browser_download_url': 'https://gh/x86_64.zsync'},
    ],
})


def test_asset_glob_resolves_download_url():
    f = fetcher({GH: RELEASE_JSON})
    spec = {'github': 'neovim/neovim', 'asset': 'nvim-linux-x86_64.appimage'}
    assert versions.discover(spec, fetch=f) == 'v0.12.4'
    assert versions.discover_asset_url(spec, fetch=f) == 'https://gh/x86_64.appimage'


def test_asset_absent_url_is_none():
    f = fetcher({GH: RELEASE_JSON})
    assert versions.discover_asset_url({'github': 'neovim/neovim'}, fetch=f) is None


# -- multi-release scan (monorepo tags / RC-latest) + tag-re -----------------
INS = 'kong/insomnia'
INS_LATEST = versions.GITHUB_LATEST.format(repo=INS)
INS_LIST = versions.GITHUB_RELEASES.format(repo=INS)


def test_asset_scan_falls_back_to_recent_releases():
    # the newest release is a different monorepo component (no Core .deb); an earlier release has it
    latest = json.dumps({'tag_name': 'inso@11.0.0', 'assets': [
        {'name': 'inso-linux-11.0.0.tar.xz', 'browser_download_url': 'https://gh/inso.txz'}]})
    listing = json.dumps([
        {'tag_name': 'inso@11.0.0', 'assets': [
            {'name': 'inso-linux-11.0.0.tar.xz', 'browser_download_url': 'https://gh/inso.txz'}]},
        {'tag_name': 'core@13.1.0', 'assets': [
            {'name': 'Insomnia.Core-13.1.0.deb', 'browser_download_url': 'https://gh/core.deb'}]}])
    f = fetcher({INS_LATEST: latest, INS_LIST: listing})
    spec = {'github': INS, 'asset': 'Insomnia.Core-*.deb'}
    assert versions.discover_asset_url(spec, fetch=f) == 'https://gh/core.deb'
    assert versions.discover(spec, fetch=f) == 'core@13.1.0'   # the MATCHING release's tag, not latest


def test_tag_re_extracts_version_from_scoped_tag():
    latest = json.dumps({'tag_name': 'core@13.1.0', 'assets': [
        {'name': 'Insomnia.Core-13.1.0.deb', 'browser_download_url': 'https://gh/core.deb'}]})
    f = fetcher({INS_LATEST: latest})
    spec = {'github': INS, 'asset': 'Insomnia.Core-*.deb', 'tag-re': '([0-9][0-9.]*)'}
    assert versions.discover(spec, fetch=f) == '13.1.0'


def test_no_release_list_fetch_when_latest_matches():
    # perf guard: when the latest release already carries the asset, the list endpoint is NOT hit
    # (the fetcher would KeyError on the un-provided list URL if it were).
    f = fetcher({GH: RELEASE_JSON})
    spec = {'github': 'neovim/neovim', 'asset': 'nvim-linux-x86_64.appimage'}
    assert versions.discover_asset_url(spec, fetch=f) == 'https://gh/x86_64.appimage'
    assert all('releases?per_page' not in u for u in f.calls)


def test_latest_failure_falls_back_to_release_list():
    # only-prerelease repo: /releases/latest 404s (fetcher raises) -> scan the list instead
    listing = json.dumps([{'tag_name': 'v2.0.0', 'assets': [
        {'name': 'tool-linux.tar.gz', 'browser_download_url': 'https://gh/t.tgz'}]}])
    f = fetcher({versions.GITHUB_RELEASES.format(repo='neovim/neovim'): listing})  # no latest URL
    spec = {'github': 'neovim/neovim', 'asset': 'tool-linux.tar.gz'}
    assert versions.discover_asset_url(spec, fetch=f) == 'https://gh/t.tgz'
    assert versions.discover(spec, fetch=f) == 'v2.0.0'


def test_asset_glob_matches_case_insensitively():
    # upstream varies Linux/linux (lazygit ships `..._linux_x86_64...`); a route glob written
    # with `Linux` must still match, else the tarball driver bails with "no url".
    rel = json.dumps({'tag_name': 'v0.63.1', 'assets': [
        {'name': 'lazygit_0.63.1_linux_x86_64.tar.gz', 'browser_download_url': 'https://gh/lg.tgz'},
        {'name': 'lazygit_0.63.1_windows_x86_64.zip', 'browser_download_url': 'https://gh/lg.zip'}]})
    url = versions.GITHUB_LATEST.format(repo='jesseduffield/lazygit')
    f = fetcher({url: rel})
    spec = {'github': 'jesseduffield/lazygit', 'asset': 'lazygit_*_Linux_x86_64.tar.gz'}
    assert versions.discover_asset_url(spec, fetch=f) == 'https://gh/lg.tgz'


def test_asset_source_key_distinguishes_patterns():
    a = versions.source_key({'github': 'r/r', 'asset': 'x-x86_64.zip'})
    b = versions.source_key({'github': 'r/r', 'asset': 'x-arm64.zip'})
    c = versions.source_key({'github': 'r/r'})
    assert a != b and a != c


def test_crates_strategy_prefers_max_stable():
    body = json.dumps({'crate': {'name': 'ts', 'max_stable_version': '0.26.11',
                                 'newest_version': '0.27.0-pre'}})
    f = fetcher({'https://crates.io/api/v1/crates/ts': body})
    assert versions.discover({'crates': 'ts'}, fetch=f) == '0.26.11'


def test_crates_strategy_falls_back_to_newest():
    body = json.dumps({'crate': {'name': 'ts', 'newest_version': '0.27.0'}})
    f = fetcher({'https://crates.io/api/v1/crates/ts': body})
    assert versions.discover({'crates': 'ts'}, fetch=f) == '0.27.0'


def test_crates_source_key():
    assert versions.source_key({'crates': 'ripgrep'}) == 'crates:ripgrep'


def test_fetch_error_returns_none_without_cache():
    def boom(url, timeout=10):
        raise OSError('offline')
    assert versions.discover({'github': 'neovim/neovim'}, fetch=boom) is None


def test_cache_hit_avoids_fetch(tmp_path):
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path), 'CONFIGSYS_STATE_DIR': str(tmp_path / 's')})
    spec = {'github': 'neovim/neovim'}
    f1 = fetcher({GH: json.dumps({'tag_name': 'v1'})})
    assert versions.discover(spec, paths, fetch=f1, now=1000) == 'v1'
    assert f1.calls == [GH]
    # within TTL -> served from cache, no fetch
    f2 = fetcher({})
    assert versions.discover(spec, paths, fetch=f2, now=1000 + 100) == 'v1'
    assert f2.calls == []


def test_ttl_expiry_refetches(tmp_path):
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path), 'CONFIGSYS_STATE_DIR': str(tmp_path / 's')})
    spec = {'github': 'neovim/neovim'}
    versions.discover(spec, paths, fetch=fetcher({GH: json.dumps({'tag_name': 'v1'})}), now=0)
    f = fetcher({GH: json.dumps({'tag_name': 'v2'})})
    got = versions.discover(spec, paths, fetch=f, now=versions.DEFAULT_TTL + 1)
    assert got == 'v2' and f.calls == [GH]


def test_refresh_bypasses_cache(tmp_path):
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path), 'CONFIGSYS_STATE_DIR': str(tmp_path / 's')})
    spec = {'github': 'neovim/neovim'}
    versions.discover(spec, paths, fetch=fetcher({GH: json.dumps({'tag_name': 'v1'})}), now=1000)
    f = fetcher({GH: json.dumps({'tag_name': 'v2'})})
    assert versions.discover(spec, paths, refresh=True, fetch=f, now=1001) == 'v2'


def test_offline_falls_back_to_stale_cache(tmp_path):
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path), 'CONFIGSYS_STATE_DIR': str(tmp_path / 's')})
    spec = {'github': 'neovim/neovim'}
    versions.discover(spec, paths, fetch=fetcher({GH: json.dumps({'tag_name': 'v1'})}), now=0)

    def boom(url, timeout=10):
        raise OSError('offline')
    # TTL expired + fetch fails -> last known value
    assert versions.discover(spec, paths, fetch=boom, now=versions.DEFAULT_TTL + 5) == 'v1'
