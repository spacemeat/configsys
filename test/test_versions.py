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


def test_asset_source_key_distinguishes_patterns():
    a = versions.source_key({'github': 'r/r', 'asset': 'x-x86_64.zip'})
    b = versions.source_key({'github': 'r/r', 'asset': 'x-arm64.zip'})
    c = versions.source_key({'github': 'r/r'})
    assert a != b and a != c


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
