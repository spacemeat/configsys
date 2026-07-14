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

import json
import re
import time
import urllib.request

from .errors import ConfigError
from .troveio import emit_hu, load

DEFAULT_TTL = 86400  # 24h
GITHUB_LATEST = 'https://api.github.com/repos/{repo}/releases/latest'


def http_fetch(url, timeout=10):
    req = urllib.request.Request(url, headers={'User-Agent': 'configsys'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', 'replace')


def source_key(spec):
    for kind in ('github', 'url', 'static'):
        if kind in spec:
            return f'{kind}:{spec[kind]}'
    return 'spec:' + json.dumps(spec, sort_keys=True)


def _discover_live(spec, fetch):
    if 'static' in spec:
        return str(spec['static'])
    if 'github' in spec:
        data = json.loads(fetch(GITHUB_LATEST.format(repo=spec['github'])))
        tag = data.get('tag_name')
        if tag and spec.get('strip-v') and tag.startswith('v'):
            tag = tag[1:]
        return tag
    if 'url' in spec:
        text = fetch(spec['url'])
        pattern = spec.get('regex') or r'[0-9]+(?:\.[0-9]+)+'
        m = re.search(pattern, text)
        return m.group(0) if m else None
    return None


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
            fetched = ch['fetched'].value if ch['fetched'] is not None else '0'
            try:
                fetched = float(fetched)
            except (TypeError, ValueError):
                fetched = 0.0
            if ver:
                recs[ch.key] = {'version': ver, 'fetched': fetched}
        return cls(recs)

    def save(self, paths):
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        obj = {k: {'version': r['version'], 'fetched': repr(r['fetched'])}
               for k, r in sorted(self.records.items())}
        paths.versions_file.write_text(emit_hu(obj), encoding='utf-8')

    def fresh(self, key, now, ttl):
        r = self.records.get(key)
        return r['version'] if r and (now - r['fetched'] <= ttl) else None

    def stale(self, key):
        r = self.records.get(key)
        return r['version'] if r else None

    def set(self, key, version, now):
        self.records[key] = {'version': version, 'fetched': now}


def discover(spec, paths=None, *, refresh=False, fetch=http_fetch, now=None,
             ttl=DEFAULT_TTL):
    '''Return the latest version for a `version:` spec, using/updating the cache.'''
    if not isinstance(spec, dict):
        return None
    if 'static' in spec:
        return str(spec['static'])           # pins never touch the network/cache

    key = source_key(spec)
    now = time.time() if now is None else now
    cache = VersionCache.load(paths) if paths is not None else VersionCache()

    if not refresh:
        cached = cache.fresh(key, now, ttl)
        if cached is not None:
            return cached

    try:
        version = _discover_live(spec, fetch)
    except Exception:
        return cache.stale(key)              # offline / fetch error -> last known

    if version:
        cache.set(key, version, now)
        if paths is not None:
            cache.save(paths)
        return version
    return cache.stale(key)
