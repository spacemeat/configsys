'''ledger.py — the small local state file (~/.config/configsys/state.hu).

The system is the source of truth for what's installed; the ledger only stores
what the OS can't tell us: version-lock *intent* (portable across drivers that
have no native hold) and whether configsys manages a component (appImages/fonts it
dropped in). Keyed by unit key `driver\\comp`. Troves are read-only, so writes go
through troveio.emit_hu.
'''

import humon as h

from .troveio import emit_hu, load

DICT = h.NodeKind.DICT


def _to_bool(s):
    return str(s).strip().lower() in ('true', '1', 'yes')


def _blank_record():
    return {'locked': False, 'managed': False, 'pinned_version': ''}


class Ledger:
    def __init__(self, records=None):
        self.records = dict(records) if records else {}

    @classmethod
    def load(cls, paths):
        p = paths.ledger_file
        if not p.exists() or not p.read_text(encoding='utf-8-sig').strip():
            return cls({})  # missing or blank ledger == no records
        trove = load(p)
        root = trove.root
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
            recs[ch.key] = rec
        return cls(recs)

    def save(self, paths):
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        obj = {
            key: {
                'locked': rec['locked'],
                'managed': rec['managed'],
                'pinned_version': rec['pinned_version'],
            }
            for key, rec in sorted(self.records.items())
        }
        paths.ledger_file.write_text(emit_hu(obj), encoding='utf-8')

    # -- accessors --------------------------------------------------------

    def _rec(self, key):
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
