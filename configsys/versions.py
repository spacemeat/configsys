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
GITHUB_LATEST = 'https://api.github.com/repos/{repo}/releases/latest'


def http_fetch(url, timeout=10):
    headers = {'User-Agent': 'configsys'}
    # A token lifts GitHub's unauthenticated 60/hr rate limit; optional.
    token = os.environ.get('CONFIGSYS_GITHUB_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if token and 'api.github.com' in url:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', 'replace')


def source_key(spec):
    # asset pattern is part of the identity (different assets -> different urls)
    if 'github' in spec:
        base = f'github:{spec["github"]}'
        return f'{base}:asset={spec["asset"]}' if spec.get('asset') else base
    for kind in ('url', 'static'):
        if kind in spec:
            return f'{kind}:{spec[kind]}'
    return 'spec:' + json.dumps(spec, sort_keys=True)


def _discover_live(spec, fetch):
    '''Return (version, download_url). download_url is only set when a github
    `asset` glob matches a release asset (authoritative URL from the API).'''
    if 'static' in spec:
        return str(spec['static']), None
    if 'github' in spec:
        data = json.loads(fetch(GITHUB_LATEST.format(repo=spec['github'])))
        tag = data.get('tag_name')
        if tag and spec.get('strip-v') and tag.startswith('v'):
            tag = tag[1:]
        url = None
        pattern = spec.get('asset')
        if pattern:
            for asset in data.get('assets', []):
                if fnmatch.fnmatch(asset.get('name', ''), pattern):
                    url = asset.get('browser_download_url')
                    break
        return tag, url
    if 'url' in spec:
        text = fetch(spec['url'])
        pattern = spec.get('regex') or r'[0-9]+(?:\.[0-9]+)+'
        m = re.search(pattern, text)
        return (m.group(0) if m else None), None
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


def _resolve(spec, paths, refresh, fetch, now, ttl):
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

    try:
        version, url = _discover_live(spec, fetch)
    except Exception:
        rec = cache.any(key)                 # offline / fetch error -> last known
        return (rec['version'], rec.get('url')) if rec else (None, None)

    if version:
        cache.set(key, version, url, now)
        if paths is not None:
            cache.save(paths)
        return version, url
    rec = cache.any(key)
    return (rec['version'], rec.get('url')) if rec else (None, None)


def discover(spec, paths=None, *, refresh=False, fetch=http_fetch, now=None,
             ttl=DEFAULT_TTL):
    '''Latest version string for a `version:` spec (uses/updates the cache).'''
    if not isinstance(spec, dict):
        return None
    return _resolve(spec, paths, refresh, fetch, now, ttl)[0]


def discover_asset_url(spec, paths=None, *, refresh=False, fetch=http_fetch, now=None,
                       ttl=DEFAULT_TTL):
    '''The github release asset download URL, if the spec has a matching `asset`
    glob; else None. Shares the cache with discover().'''
    if not isinstance(spec, dict):
        return None
    return _resolve(spec, paths, refresh, fetch, now, ttl)[1]
