'''ledger.py — the small local state file (~/.config/configsys/state.hu).

The system is the source of truth for what's installed; the ledger only stores
what the OS can't tell us: version-lock *intent* (portable across drivers that
have no native hold), whether configsys manages a component (appImages/fonts it
dropped in), and an install RECEIPT — the unit configsys installed (`via`, package
`name`, the driver `fields`) — so an install stays findable and removable after
routes stop offering that method (an AUR package promoted to pacman, a dropped
AppImage; see stranded.py). Keyed by unit key `driver\\comp`. Troves are read-only,
so writes go through troveio.emit_hu.
'''

import humon as h

from .troveio import emit_hu, load

DICT = h.NodeKind.DICT


def _to_bool(s):
    from .layers import parse_bool                 # the one bool spelling (D1)
    return parse_bool(s, False)


def _blank_record():
    return {'locked': False, 'managed': False, 'pinned_version': '', 'receipt': None}


# config drivers: what they link isn't an install METHOD of the component, so no receipt
_NO_RECEIPT = frozenset({'dotfiles', 'glue'})


class Ledger:
    def __init__(self, records=None):
        self.records = dict(records) if records else {}
        self.changed = set()            # keys this process set/cleared — all a save writes back
        self.corrupt = None             # the unreadable file this load fell back from, if any

    @classmethod
    def load(cls, paths):
        p = paths.ledger_file
        try:
            if not p.exists() or not p.read_text(encoding='utf-8-sig').strip():
                return cls({})  # missing or blank ledger == no records
            return cls(cls._parse(p))
        except Exception:                          # noqa: BLE001 — a torn/garbled state.hu: never a brick
            led = cls({})                          # (B10) — run on, empty; the save moves it aside
            led.corrupt = p
            return led

    @classmethod
    def _parse(cls, p):
        trove = load(p)
        root = trove.root
        try:                                       # receipts are nested maps: read them materialized
            from .layers import materialize_string
            raw = materialize_string(p.read_text(encoding='utf-8-sig')) or {}
        except Exception:                          # noqa: BLE001 — a bad receipt never loses locks
            raw = {}
        recs = {}
        for i in range(root.num_children):
            ch = root[i]
            rec = _blank_record()
            if ch.kind == DICT:
                if ch['locked'] is not None:
                    rec['locked'] = _to_bool(ch['locked'].value)
                if ch['managed'] is not None:
                    rec['managed'] = _to_bool(ch['managed'].value)
                if ch['pinned_version'] is not None:
                    rec['pinned_version'] = ch['pinned_version'].value or ''
                r = (raw.get(ch.key) or {}).get('receipt') if isinstance(raw.get(ch.key), dict) else None
                if isinstance(r, dict) and r.get('via') and r.get('name'):
                    rec['receipt'] = {'via': str(r['via']), 'name': str(r['name']),
                                      'fields': r.get('fields') if isinstance(r.get('fields'), dict) else {}}
                    if r.get('source'):            # the defining layer (A1 — kept across a reload)
                        rec['receipt']['source'] = str(r['source'])
            recs[ch.key] = rec
        return recs

    def save(self, paths):
        '''Write back ONLY what this process changed, merged into the file as it is NOW, under an
        exclusive lock, atomically (B10): a TUI that loaded the ledger an hour ago no longer
        overwrites the locks and receipts a CLI run saved meanwhile, and a crash mid-write can't
        leave a torn file. An unreadable file this load fell back from is moved aside first.'''
        import fcntl
        import os
        import time
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        lock_path = paths.ledger_file.with_name(paths.ledger_file.name + '.lock')
        with open(lock_path, 'a') as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            if self.corrupt is not None and paths.ledger_file.exists():
                os.replace(paths.ledger_file,
                           paths.ledger_file.with_name(f'{paths.ledger_file.name}.corrupt-{int(time.time())}'))
                self.corrupt = None
            disk = Ledger.load(paths)
            merged = dict(disk.records) if disk.corrupt is None else {}
            for key in self.changed:
                if key in self.records:
                    merged[key] = self.records[key]
            self.records = merged
            self._write(paths)
            self.changed.clear()

    def _write(self, paths):
        import os
        obj = {}
        for key, rec in sorted(self.records.items()):
            out = {'locked': rec['locked'], 'managed': rec['managed'],
                   'pinned_version': rec['pinned_version']}
            if rec.get('receipt'):
                out['receipt'] = rec['receipt']
            obj[key] = out
        tmp = paths.ledger_file.with_name(paths.ledger_file.name + '.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(emit_hu(obj))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, paths.ledger_file)

    # -- accessors --------------------------------------------------------

    def _rec(self, key):
        self.changed.add(key)                      # every setter goes through here
        return self.records.setdefault(key, _blank_record())

    def is_locked(self, key):
        return self.records.get(key, {}).get('locked', False)

    def is_managed(self, key):
        return self.records.get(key, {}).get('managed', False)

    def pinned_version(self, key):
        return self.records.get(key, {}).get('pinned_version', '')

    def set_lock(self, key, value):
        self._rec(key)['locked'] = bool(value)

    def set_managed(self, key, value):
        self._rec(key)['managed'] = bool(value)

    def set_pinned(self, key, value):
        self._rec(key)['pinned_version'] = value or ''

    # -- install receipts (see stranded.py) --------------------------------

    def set_receipt(self, rc):
        '''Record that configsys installed unit `rc` (after a successful install/upgrade/
        set-version): enough to find + remove it even once routes no longer offer the method.'''
        if rc.driver in _NO_RECEIPT:
            return
        fields = {k: v for k, v in (rc.fields or {}).items() if k != 'name'}
        rec = {'via': rc.via or rc.driver, 'name': rc.name, 'fields': fields}
        if getattr(rc, 'source', ''):
            # the layer that defined the binding: a replayed receipt is trusted exactly as that layer
            # is NOW (an untrusted or removed plugin's recorded commands don't run — review A1/actions-07)
            rec['source'] = str(rc.source)
        self._rec(rc.key)['receipt'] = rec

    def clear_receipt(self, key):
        if key in self.records:
            self.records[key]['receipt'] = None
            self.changed.add(key)

    def receipt(self, key):
        return self.records.get(key, {}).get('receipt')

    def receipts_for(self, comp):
        '''{unit_key: receipt} for every recorded install of component `comp` (any driver).'''
        return {k: r['receipt'] for k, r in self.records.items()
                if r.get('receipt') and k.split('\\', 1)[-1] == comp}
