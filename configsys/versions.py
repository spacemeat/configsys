'''versions.py — discover the latest available version of download-based software.

Routes declare *how* to find the latest version instead of hardcoding it:

    version: { github: neovim/neovim }              # latest release tag
    version: { github: arduino/arduino-ide  strip-v: true }
    version: { url: "https://.../latest.txt"  regex: "[0-9.]+" }   # fetch + extract
    version: { static: 1.4.350.1 }                  # a deliberate pin

Discovery is networked, so results are cached (state_dir/versions.hu) with a TTL;
`refresh=True` bypasses the TTL. Offline / fetch failure falls back to any cached
value, then None. The fetcher is injectable for testing.
'''

import fnmatch
import json
import os
import re
import time
import urllib.request

from .errors import ConfigError
from .troveio import emit_hu, load

DEFAULT_TTL = 86400  # 24h
# Version (tag) discovery uses GitHub's ANONYMOUS web feeds — github.com, NOT api.github.com — so
# it is NOT subject to the API's 60/hr unauthenticated rate limit. `refresh` queries many
# components at once, so this is the path that has to scale token-free. The api.github.com
# endpoints below are used ONLY to resolve a release ASSET url (a glob the feed can't answer),
# which happens lazily at install time for a single component — well under the limit.
GITHUB_RELEASES_ATOM = 'https://github.com/{repo}/releases.atom'
GITHUB_TAGS_ATOM = 'https://github.com/{repo}/tags.atom'
GITHUB_LATEST = 'https://api.github.com/repos/{repo}/releases/latest'
GITHUB_RELEASES = 'https://api.github.com/repos/{repo}/releases?per_page=30'


def http_fetch(url, timeout=10):
    headers = {'User-Agent': 'configsys'}
    # A token lifts GitHub's unauthenticated 60/hr rate limit; optional.
    token = os.environ.get('CONFIGSYS_GITHUB_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if token and 'api.github.com' in url:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', 'replace')


CRATES_LATEST = 'https://crates.io/api/v1/crates/{crate}'
PYPI_LATEST = 'https://pypi.org/pypi/{dist}/json'
AUR_INFO = 'https://aur.archlinux.org/rpc/v5/info?arg[]={pkg}'
HACKAGE_PREFERRED = 'https://hackage.haskell.org/package/{pkg}/preferred.json'


# Registered version-discovery sources (P2c): plugins add new `version: { <name>: ... }`
# backends here. name -> fn(spec, fetch) -> (version, download_url_or_None). Registration
# happens only from trusted plugin code (via plugins.load_code), so the trust gate is inherent.
_SOURCES = {}
_BUILTIN_KINDS = ('crates', 'pypi', 'aur', 'hackage', 'url', 'static')


def register_source(name, fn):
    '''Register a version-discovery source so `version: { <name>: <arg> }` resolves. `fn(spec,
    fetch) -> (version, download_url_or_None)`; `fetch(url)` is the injectable HTTP getter, so
    caching/offline fallback stay in the core. Built-in kinds (github/crates/pypi/aur/url/
    static) win over a registered name of the same key. Re-exported as register_version_source.'''
    if not name or not callable(fn):
        raise ValueError('register_source(name, fn): name must be non-empty and fn callable')
    _SOURCES[name] = fn
    return fn


def source_key(spec):
    # asset pattern is part of the identity (different assets -> different urls)
    if 'github' in spec:
        base = f'github:{spec["github"]}'
        return f'{base}:asset={spec["asset"]}' if spec.get('asset') else base
    if 'pypi' in spec:
        base = f'pypi:{spec["pypi"]}'
        return f'{base}@py{spec["python"]}' if spec.get('python') else base   # python-scoped latest
    for kind in (*_BUILTIN_KINDS, *_SOURCES):
        if kind in spec:
            return f'{kind}:{spec[kind]}'
    return 'spec:' + json.dumps(spec, sort_keys=True)


def _match_release(rel, pattern):
    '''(tag, asset-download-url) for one GitHub release JSON. url is None when `pattern` is falsy
    or no asset name matches the glob (case-insensitive — upstream varies Linux/linux).'''
    tag = rel.get('tag_name')
    if pattern:
        pat = pattern.lower()
        for asset in rel.get('assets', []):
            if fnmatch.fnmatch(asset.get('name', '').lower(), pat):
                return tag, asset.get('browser_download_url')
    return tag, None


_ATOM_TAG_RE = re.compile(r'/releases/tag/([^"<]+)')
_ATOM_TITLE_RE = re.compile(r'<title>([^<]*)</title>')


def _github_atom_tags(fetch, repo):
    '''Recent tags newest-first from GitHub's ANONYMOUS web feeds (github.com, so no 60/hr API
    limit). releases.atom carries release tags in `/releases/tag/<TAG>` links; tags.atom is the
    fallback for repos that tag without cutting GitHub "releases" (tag in the entry <title>).'''
    import html as _html
    from urllib.parse import unquote
    for tmpl in (GITHUB_RELEASES_ATOM, GITHUB_TAGS_ATOM):
        try:
            xml = fetch(tmpl.format(repo=repo))
        except Exception:
            continue
        tags = _ATOM_TAG_RE.findall(xml)
        if not tags:                       # tags.atom: the tag lives in <title> (first is the feed's own)
            titles = _ATOM_TITLE_RE.findall(xml)
            tags = titles[1:] if len(titles) > 1 else []
        if tags:
            # a tag from a /releases/tag/<TAG> link is URL-ENCODED — a monorepo scope tag like
            # `core@13.2.0` arrives as `core%4013.2.0`, and the `%40` would feed a stray `40` into a
            # numeric tag-re (-> 4013.2.0). Percent-decode before anything reads it.
            return [_html.unescape(unquote(t.strip())) for t in tags]
    return []


def _tag_transform(tag, spec):
    '''Apply `tag-re:` (extract the version out of a decorated tag — a monorepo scope `core@13.1.0`
    or a channel suffix `4.7.1-stable`; first capture group, else whole match) then `strip-v:`.'''
    if not tag:
        return tag
    tre = spec.get('tag-re')
    if tre:
        m = re.search(tre, tag)
        if m:
            tag = m.group(1) if m.groups() else m.group(0)
    if spec.get('strip-v') and tag.startswith('v'):
        tag = tag[1:]
    return tag


def _select_github_tag(tags, spec):
    '''Pick the version from an atom feed's newest-first tag list. With `tag-re:`, prefer the newest
    RAW tag that matches it (a monorepo that interleaves several components' tags), else the newest.'''
    chosen = None
    tre = spec.get('tag-re')
    if tre:
        for t in tags:
            if re.search(tre, t):
                chosen = t
                break
    if chosen is None and tags:
        chosen = tags[0]
    return _tag_transform(chosen, spec) if chosen else None


def _github_asset_url_live(spec, fetch):
    '''(version, asset_url) via api.github.com — the ONLY way to enumerate release assets for a
    glob. Called lazily at INSTALL time for one component, so the 60/hr API limit is a non-issue
    here (and http_fetch applies a token if one happens to be set). Mirrors the old scan: try the
    `latest` shortcut, then walk recent releases for the one that actually carries the asset (an
    RC/monorepo newest release may not).'''
    repo, pattern = spec['github'], spec.get('asset')
    if not pattern:
        return None, None
    tag = url = None
    try:
        tag, url = _match_release(json.loads(fetch(GITHUB_LATEST.format(repo=repo))), pattern)
    except Exception:
        pass
    if url is None:
        try:
            for rel in json.loads(fetch(GITHUB_RELEASES.format(repo=repo))):
                t, u = _match_release(rel, pattern)
                if tag is None:
                    tag = t
                if u is not None:
                    tag, url = t, u
                    break
        except Exception:
            pass
    return _tag_transform(tag, spec), url


def _pypi_latest_for_python(data, pyver):
    '''The newest stable PyPI release of a dist whose `requires_python` ADMITS the interpreter
    `pyver` (e.g. "3.10.12" or "Python 3.10.12"). This is what pipx would actually be able to
    upgrade a venv to — a package can publish a newer release that drops old pythons (pywal16 3.8.15
    needs >=3.11), and reporting THAT as "latest" for a 3.10 venv makes it read outdated when it
    can't move. Falls back to the absolute latest when nothing is judgeable.'''
    from packaging.version import Version, InvalidVersion
    from packaging.specifiers import SpecifierSet, InvalidSpecifier
    m = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', str(pyver))
    absolute = data.get('info', {}).get('version')
    if not m:
        return absolute
    py = f'{m.group(1)}.{m.group(2)}.{m.group(3) or 0}'
    best = None
    for ver, files in (data.get('releases') or {}).items():
        if not files:
            continue                          # no artifacts (yanked/registered-only) -> skip
        rp = files[0].get('requires_python')  # PyPI sets requires_python per release (files agree)
        try:
            if rp and py not in SpecifierSet(rp):
                continue
            v = Version(ver)
        except (InvalidSpecifier, InvalidVersion):
            continue
        if v.is_prerelease:
            continue                          # match info.version's stable-only semantics
        if best is None or v > best[0]:
            best = (v, ver)
    return best[1] if best else absolute


def _discover_live(spec, fetch):
    '''Return (version, download_url). download_url is only set when a github
    `asset` glob matches a release asset (authoritative URL from the API).'''
    if 'static' in spec:
        return str(spec['static']), None
    if 'github' in spec:
        # VERSION only, via the anonymous atom feed (no api.github.com rate limit). The asset url
        # (when an `asset` glob is present) is resolved separately + lazily by _github_asset_url_live
        # at install time — the feed can't enumerate assets. The newest tag is what we want; for a
        # monorepo with a `tag-re:`, _select_github_tag filters to the newest matching tag.
        return _select_github_tag(_github_atom_tags(fetch, spec['github']), spec), None
    if 'crates' in spec:
        data = json.loads(fetch(CRATES_LATEST.format(crate=spec['crates'])))
        c = data.get('crate', {})
        v = c.get('max_stable_version') or c.get('newest_version') or c.get('max_version')
        return v, None
    if 'pypi' in spec:
        data = json.loads(fetch(PYPI_LATEST.format(dist=spec['pypi'])))
        if spec.get('python'):               # latest RELEASE whose requires_python admits this python
            return _pypi_latest_for_python(data, spec['python']), None
        return data.get('info', {}).get('version'), None
    if 'aur' in spec:
        data = json.loads(fetch(AUR_INFO.format(pkg=spec['aur'])))
        results = data.get('results') or []
        return (results[0].get('Version') if results else None), None
    if 'hackage' in spec:
        # Hackage's preferred.json lists non-deprecated versions newest-first in `normal-version`
        data = json.loads(fetch(HACKAGE_PREFERRED.format(pkg=spec['hackage'])))
        vers = data.get('normal-version') or []
        return (vers[0] if vers else None), None
    if 'url' in spec:
        text = fetch(spec['url'])
        pattern = spec.get('regex') or r'[0-9]+(?:\.[0-9]+)+'
        m = re.search(pattern, text)
        if not m:
            return None, None
        # a capture group extracts the version out of surrounding text (e.g. the rust stable
        # channel manifest's `[pkg.rust]\nversion = "1.97.1 (...)"`); groupless regexes match it
        # directly, as before.
        return (m.group(1) if m.groups() else m.group(0)), None
    for name, fn in _SOURCES.items():            # plugin-registered sources (P2c)
        if name in spec:
            return fn(spec, fetch)
    return None, None


class VersionCache:
    def __init__(self, records=None):
        self.records = dict(records) if records else {}

    @classmethod
    def load(cls, paths):
        p = paths.versions_file
        if not p.exists() or not p.read_text(encoding='utf-8-sig').strip():
            return cls({})
        try:
            trove = load(p)          # keep the trove alive while walking its nodes
        except ConfigError:
            return cls({})
        root = trove.root
        recs = {}
        for i in range(root.num_children):
            ch = root[i]
            ver = ch['version'].value if ch['version'] is not None else None
            url = ch['url'].value if ch['url'] is not None else None
            fetched = ch['fetched'].value if ch['fetched'] is not None else '0'
            try:
                fetched = float(fetched)
            except (TypeError, ValueError):
                fetched = 0.0
            if ver:
                recs[ch.key] = {'version': ver, 'url': url, 'fetched': fetched}
        return cls(recs)

    def save(self, paths):
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        obj = {}
        for k, r in sorted(self.records.items()):
            rec = {'version': r['version'], 'fetched': repr(r['fetched'])}
            if r.get('url'):
                rec['url'] = r['url']
            obj[k] = rec
        paths.versions_file.write_text(emit_hu(obj), encoding='utf-8')

    def get(self, key, now, ttl):
        r = self.records.get(key)
        return r if r and (now - r['fetched'] <= ttl) else None

    def any(self, key):
        return self.records.get(key)

    def set(self, key, version, url, now):
        self.records[key] = {'version': version, 'url': url, 'fetched': now}


def _resolve(spec, paths, refresh, fetch, now, ttl, offline=False):
    '''-> (version, download_url) via the cache.'''
    if 'static' in spec:
        return str(spec['static']), None     # pins never touch the network/cache

    key = source_key(spec)
    now = time.time() if now is None else now
    cache = VersionCache.load(paths) if paths is not None else VersionCache()

    if not refresh:
        rec = cache.get(key, now, ttl)
        if rec is not None:
            return rec['version'], rec.get('url')

    if offline:
        # dry-run (--pretend): never touch the network. Use the last-known cache, else nothing.
        rec = cache.any(key)
        return (rec['version'], rec.get('url')) if rec else (None, None)

    try:
        version, url = _discover_live(spec, fetch)
    except Exception:
        rec = cache.any(key)                 # offline / fetch error -> last known
        return (rec['version'], rec.get('url')) if rec else (None, None)

    if version:
        if url is None:                      # version-only source (github atom, crates, …): keep any
            prev = cache.any(key)            # asset url already resolved for this key by _resolve_asset
            url = prev.get('url') if prev else None
        cache.set(key, version, url, now)
        if paths is not None:
            cache.save(paths)
        return version, url
    rec = cache.any(key)
    return (rec['version'], rec.get('url')) if rec else (None, None)


def _resolve_asset(spec, paths, refresh, fetch, now, ttl, offline):
    '''-> the github release asset url (glob) via the cache, hitting api.github.com lazily. Only
    github+asset specs have one; everything else is None. Separate from _resolve so that VERSION
    discovery (the refresh-heavy path) never touches the API.'''
    if 'github' not in spec or not spec.get('asset'):
        return None
    key = source_key(spec)
    now = time.time() if now is None else now
    cache = VersionCache.load(paths) if paths is not None else VersionCache()

    if not refresh:
        rec = cache.get(key, now, ttl)
        if rec is not None and rec.get('url'):
            return rec['url']
    if offline:                              # --pretend: cache-or-None, never the network
        rec = cache.any(key)
        return rec.get('url') if rec else None

    try:
        version, url = _github_asset_url_live(spec, fetch)
    except Exception:
        rec = cache.any(key)
        return rec.get('url') if rec else None
    if url:
        rec = cache.any(key)
        ver = version or (rec['version'] if rec else None) or ''
        cache.set(key, ver, url, now)        # ver is non-empty (the API returns the tag too)
        if paths is not None:
            cache.save(paths)
        return url
    rec = cache.any(key)
    return rec.get('url') if rec else None


def discover(spec, paths=None, *, refresh=False, fetch=http_fetch, now=None,
             ttl=DEFAULT_TTL, offline=False):
    '''Latest version string for a `version:` spec (uses/updates the cache). `offline` never
    hits the network (for --pretend): cache-or-None. GitHub versions come from the anonymous
    atom feed — no api.github.com rate limit.'''
    if not isinstance(spec, dict):
        return None
    return _resolve(spec, paths, refresh, fetch, now, ttl, offline)[0]


def discover_asset_url(spec, paths=None, *, refresh=False, fetch=http_fetch, now=None,
                       ttl=DEFAULT_TTL, offline=False):
    '''The github release asset download URL, if the spec has a matching `asset` glob; else None.
    Shares the cache with discover(). Resolved via api.github.com — but lazily, at install time,
    for a single component (never the refresh-time fan-out). `offline` skips the network.'''
    if not isinstance(spec, dict):
        return None
    return _resolve_asset(spec, paths, refresh, fetch, now, ttl, offline)
