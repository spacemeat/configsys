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


# Version (tag) discovery reads the ANONYMOUS atom feed (github.com, no API rate limit); asset-url
# resolution still uses api.github.com (GH), but only lazily at install time for one component.
GH = 'https://api.github.com/repos/neovim/neovim/releases/latest'


def atom(repo, tags):
    '''A minimal releases.atom feed: entries newest-first, tag in each /releases/tag/<t> link.'''
    entries = ''.join(
        f'<entry><link href="https://github.com/{repo}/releases/tag/{t}"/></entry>' for t in tags)
    return f'<?xml version="1.0"?><feed><title>Release notes</title>{entries}</feed>'


def atom_url(repo):
    return versions.GITHUB_RELEASES_ATOM.format(repo=repo)


def test_static_never_fetches():
    f = fetcher({})
    assert versions.discover({'static': '1.2.3'}, fetch=f) == '1.2.3'
    assert f.calls == []


def test_github_tag():
    repo = 'neovim/neovim'
    f = fetcher({atom_url(repo): atom(repo, ['v0.10.2', 'v0.10.1'])})
    assert versions.discover({'github': repo}, fetch=f) == 'v0.10.2'


def test_github_strip_v():
    repo = 'neovim/neovim'
    f = fetcher({atom_url(repo): atom(repo, ['v0.10.2'])})
    assert versions.discover({'github': repo, 'strip-v': True}, fetch=f) == '0.10.2'


def test_version_discovery_never_hits_the_api():
    # the whole point: a GitHub *version* lookup must not touch api.github.com (60/hr). Only the
    # atom url is provided, so if discover reached for the API the fetcher would KeyError.
    repo = 'neovim/neovim'
    f = fetcher({atom_url(repo): atom(repo, ['v9.9.9'])})
    assert versions.discover({'github': repo}, fetch=f) == 'v9.9.9'
    assert all('api.github.com' not in u for u in f.calls)


def test_tags_atom_fallback_when_no_releases():
    # a repo that tags without cutting GitHub "releases": releases.atom is empty, tags.atom answers.
    repo = 'some/lib'
    tags_feed = ('<?xml version="1.0"?><feed><title>Tags</title>'
                 '<entry><title>v3.2.1</title></entry><entry><title>v3.2.0</title></entry></feed>')
    f = fetcher({atom_url(repo): '<feed><title>Releases</title></feed>',
                 versions.GITHUB_TAGS_ATOM.format(repo=repo): tags_feed})
    assert versions.discover({'github': repo}, fetch=f) == 'v3.2.1'


def test_url_regex_extract():
    f = fetcher({'https://x/latest.txt': '  version 1.4.350.1 released\n'})
    assert versions.discover({'url': 'https://x/latest.txt'}, fetch=f) == '1.4.350.1'


def test_hackage_preferred_newest_first():
    # Hackage's preferred.json lists non-deprecated versions newest-first in `normal-version`
    url = 'https://hackage.haskell.org/package/hlint/preferred.json'
    f = fetcher({url: json.dumps({'deprecated-version': ['2.1.19'],
                                  'normal-version': ['3.10', '3.8', '3.6.1']})})
    assert versions.discover({'hackage': 'hlint'}, fetch=f) == '3.10'


def test_hackage_empty_is_none():
    url = 'https://hackage.haskell.org/package/nope/preferred.json'
    f = fetcher({url: json.dumps({'normal-version': []})})
    assert versions.discover({'hackage': 'nope'}, fetch=f) is None


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
    # version from the atom feed; asset url from the API (both mocked).
    repo = 'neovim/neovim'
    f = fetcher({atom_url(repo): atom(repo, ['v0.12.4']), GH: RELEASE_JSON})
    spec = {'github': repo, 'asset': 'nvim-linux-x86_64.appimage'}
    assert versions.discover(spec, fetch=f) == 'v0.12.4'
    assert versions.discover_asset_url(spec, fetch=f) == 'https://gh/x86_64.appimage'


def test_asset_absent_url_is_none():
    # no `asset` glob -> no asset url (and no API call at all).
    f = fetcher({})
    assert versions.discover_asset_url({'github': 'neovim/neovim'}, fetch=f) is None
    assert f.calls == []


# -- multi-release scan (monorepo tags / RC-latest) + tag-re -----------------
INS = 'kong/insomnia'
INS_LATEST = versions.GITHUB_LATEST.format(repo=INS)
INS_LIST = versions.GITHUB_RELEASES.format(repo=INS)


def test_asset_scan_falls_back_to_recent_releases():
    # asset-url resolution (API) scans recent releases for the one that carries the Core .deb — the
    # newest release is a different monorepo component (no Core asset).
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


def test_asset_resolution_corrects_cached_version(tmp_path):
    # a monorepo WITHOUT tag-re: the atom feed's newest tag is another component's, but resolving the
    # asset url (API) records the asset-bearing release's tag, so the cached version self-corrects.
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path), 'CONFIGSYS_STATE_DIR': str(tmp_path / 's')})
    latest = json.dumps({'tag_name': 'inso@11.0.0', 'assets': []})
    listing = json.dumps([
        {'tag_name': 'inso@11.0.0', 'assets': []},
        {'tag_name': 'core@13.1.0', 'assets': [
            {'name': 'Insomnia.Core-13.1.0.deb', 'browser_download_url': 'https://gh/core.deb'}]}])
    f = fetcher({atom_url(INS): atom(INS, ['inso@11.0.0', 'core@13.1.0']),
                 INS_LATEST: latest, INS_LIST: listing})
    spec = {'github': INS, 'asset': 'Insomnia.Core-*.deb'}
    assert versions.discover(spec, paths, fetch=f, now=0) == 'inso@11.0.0'      # atom newest
    assert versions.discover_asset_url(spec, paths, fetch=f, now=0) == 'https://gh/core.deb'
    # cache now reflects the asset-bearing release's tag
    assert versions.discover(spec, paths, fetch=fetcher({}), now=0) == 'core@13.1.0'


def test_tag_re_extracts_version_from_scoped_tag():
    # with tag-re, version discovery filters the atom tags to the newest matching one.
    f = fetcher({atom_url(INS): atom(INS, ['inso@11.0.0', 'core@13.1.0'])})
    spec = {'github': INS, 'asset': 'Insomnia.Core-*.deb', 'tag-re': r'core@([0-9][0-9.]*)'}
    assert versions.discover(spec, fetch=f) == '13.1.0'


def test_atom_tag_is_url_decoded():
    # GitHub's atom feed URL-ENCODES the tag: a monorepo scope tag `core@13.2.0` arrives as
    # `core%4013.2.0`. Without percent-decoding, the `%40` feeds a stray 40 into a numeric tag-re
    # -> `4013.2.0` (always "newer" than reality, so the tool reads perpetually outdated). Regression.
    feed = ('<?xml version="1.0"?><feed><title>Releases</title>'
            f'<entry><link href="https://github.com/{INS}/releases/tag/core%4013.2.0"/></entry>'
            f'<entry><link href="https://github.com/{INS}/releases/tag/core%4013.1.0"/></entry></feed>')
    f = fetcher({atom_url(INS): feed})
    assert versions.discover({'github': INS, 'tag-re': '([0-9][0-9.]*)'}, fetch=f) == '13.2.0'


def test_no_release_list_fetch_when_latest_matches():
    # perf guard: when the latest release already carries the asset, the list endpoint is NOT hit.
    f = fetcher({GH: RELEASE_JSON})
    spec = {'github': 'neovim/neovim', 'asset': 'nvim-linux-x86_64.appimage'}
    assert versions.discover_asset_url(spec, fetch=f) == 'https://gh/x86_64.appimage'
    assert all('releases?per_page' not in u for u in f.calls)


def test_latest_failure_falls_back_to_release_list():
    # asset-url: /releases/latest 404s (fetcher raises) -> scan the list instead.
    repo = 'neovim/neovim'
    listing = json.dumps([{'tag_name': 'v2.0.0', 'assets': [
        {'name': 'tool-linux.tar.gz', 'browser_download_url': 'https://gh/t.tgz'}]}])
    f = fetcher({versions.GITHUB_RELEASES.format(repo=repo): listing,   # no latest URL
                 atom_url(repo): atom(repo, ['v2.0.0'])})
    spec = {'github': repo, 'asset': 'tool-linux.tar.gz'}
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
    repo = 'neovim/neovim'
    spec = {'github': repo}
    f1 = fetcher({atom_url(repo): atom(repo, ['v1'])})
    assert versions.discover(spec, paths, fetch=f1, now=1000) == 'v1'
    assert f1.calls == [atom_url(repo)]
    # within TTL -> served from cache, no fetch
    f2 = fetcher({})
    assert versions.discover(spec, paths, fetch=f2, now=1000 + 100) == 'v1'
    assert f2.calls == []


def test_ttl_expiry_refetches(tmp_path):
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path), 'CONFIGSYS_STATE_DIR': str(tmp_path / 's')})
    repo = 'neovim/neovim'
    spec = {'github': repo}
    versions.discover(spec, paths, fetch=fetcher({atom_url(repo): atom(repo, ['v1'])}), now=0)
    f = fetcher({atom_url(repo): atom(repo, ['v2'])})
    got = versions.discover(spec, paths, fetch=f, now=versions.DEFAULT_TTL + 1)
    assert got == 'v2' and f.calls == [atom_url(repo)]


def test_refresh_bypasses_cache(tmp_path):
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path), 'CONFIGSYS_STATE_DIR': str(tmp_path / 's')})
    repo = 'neovim/neovim'
    spec = {'github': repo}
    versions.discover(spec, paths, fetch=fetcher({atom_url(repo): atom(repo, ['v1'])}), now=1000)
    f = fetcher({atom_url(repo): atom(repo, ['v2'])})
    assert versions.discover(spec, paths, refresh=True, fetch=f, now=1001) == 'v2'


def test_offline_falls_back_to_stale_cache(tmp_path):
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path), 'CONFIGSYS_STATE_DIR': str(tmp_path / 's')})
    repo = 'neovim/neovim'
    spec = {'github': repo}
    versions.discover(spec, paths, fetch=fetcher({atom_url(repo): atom(repo, ['v1'])}), now=0)

    def boom(url, timeout=10):
        raise OSError('offline')
    # TTL expired + fetch fails -> last known value
    assert versions.discover(spec, paths, fetch=boom, now=versions.DEFAULT_TTL + 5) == 'v1'
