'''cachefile.py — the machine-local TTL record caches (`versions.hu`: discovered upstream versions;
`method-versions.hu`: each install method's `get_latest`), one class instead of two hand copies
(review-2026-11-2 C4).

A cache is a humon map `{ key: { version  fetched  [url] } }` in the state dir. A parsed file is
memoized per (path, mtime, size), so a per-unit `load` on the inspect thread pool costs a dict copy,
not a parse; a save is atomic (temp file + rename), so a concurrent reader sees the old file or the
new one, never half of one — a torn read used to come back EMPTY and refetch from the network; and a
cache saves only when something was `set` since it was loaded.'''

import os
import threading

from .errors import ConfigError

_MEMO_LOCK = threading.Lock()


class TTLRecords:
    path_attr = None          # the Paths attribute naming the file (subclasses set it)
    extra_fields = ()         # record fields beyond version/fetched, kept when present
    _memo = None              # {path: ((path, mtime_ns, size), records)} — per subclass

    def __init__(self, records=None, *, loaded=False):
        self.records = dict(records) if records else {}
        self.dirty = bool(records) and not loaded      # records handed in (not read back) are new

    @classmethod
    def _file(cls, paths):
        return getattr(paths, cls.path_attr)

    @classmethod
    def load(cls, paths):
        p = cls._file(paths)
        try:
            st = p.stat()
        except OSError:
            return cls({}, loaded=True)
        key = (str(p), st.st_mtime_ns, st.st_size)
        with _MEMO_LOCK:
            memo = cls.__dict__.get('_memo')
            if memo is None:
                memo = {}
                cls._memo = memo
            hit = memo.get(str(p))
        if hit is not None and hit[0] == key:
            return cls({k: dict(v) for k, v in hit[1].items()}, loaded=True)
        recs = cls._parse(p)
        with _MEMO_LOCK:
            cls._memo[str(p)] = (key, {k: dict(v) for k, v in recs.items()})
        return cls(recs, loaded=True)

    @classmethod
    def _parse(cls, p):
        from .layers import materialize_string
        try:
            text = p.read_text(encoding='utf-8-sig')
            data = materialize_string(text) if text.strip() else {}
        except (OSError, ConfigError, Exception):      # noqa: BLE001 — unreadable = empty
            return {}
        recs = {}
        for k, ch in (data.items() if isinstance(data, dict) else ()):
            if not isinstance(ch, dict):
                continue
            try:
                fetched = float(ch.get('fetched') or 0)
            except (TypeError, ValueError):
                fetched = 0.0
            rec = {'version': ch.get('version') or None, 'fetched': fetched}
            for f in cls.extra_fields:
                rec[f] = ch.get(f)
            if cls._keep(rec):
                recs[str(k)] = rec
        return recs

    @classmethod
    def _keep(cls, rec):
        return True

    def save(self, paths):
        if not self.dirty:
            return
        from .troveio import emit_hu
        p = self._file(paths)
        p.parent.mkdir(parents=True, exist_ok=True)
        obj = {}
        for k, r in sorted(self.records.items()):
            rec = {'version': r.get('version') or '', 'fetched': repr(r['fetched'])}
            for f in self.extra_fields:
                if r.get(f):
                    rec[f] = r[f]
            obj[k] = rec
        tmp = p.with_name(p.name + '.tmp')
        tmp.write_text(emit_hu(obj), encoding='utf-8')
        os.replace(tmp, p)
        self.dirty = False

    def get(self, key, now, ttl):
        r = self.records.get(key)
        return r if (r and now - r['fetched'] <= ttl) else None

    def any(self, key):
        return self.records.get(key)
