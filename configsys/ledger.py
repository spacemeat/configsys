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
    return str(s).strip().lower() in ('true', '1', 'yes')


def _blank_record():
    return {'locked': False, 'managed': False, 'pinned_version': '', 'receipt': None}


# config drivers: what they link isn't an install METHOD of the component, so no receipt
_NO_RECEIPT = frozenset({'dotfiles', 'glue'})


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
            recs[ch.key] = rec
        return cls(recs)

    def save(self, paths):
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        obj = {}
        for key, rec in sorted(self.records.items()):
            out = {'locked': rec['locked'], 'managed': rec['managed'],
                   'pinned_version': rec['pinned_version']}
            if rec.get('receipt'):
                out['receipt'] = rec['receipt']
            obj[key] = out
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

    # -- install receipts (see stranded.py) --------------------------------

    def set_receipt(self, rc):
        '''Record that configsys installed unit `rc` (after a successful install/upgrade/
        set-version): enough to find + remove it even once routes no longer offer the method.'''
        if rc.driver in _NO_RECEIPT:
            return
        fields = {k: v for k, v in (rc.fields or {}).items() if k != 'name'}
        self._rec(rc.key)['receipt'] = {'via': rc.via or rc.driver, 'name': rc.name, 'fields': fields}

    def clear_receipt(self, key):
        if key in self.records:
            self.records[key]['receipt'] = None

    def receipt(self, key):
        return self.records.get(key, {}).get('receipt')

    def receipts_for(self, comp):
        '''{unit_key: receipt} for every recorded install of component `comp` (any driver).'''
        return {k: r['receipt'] for k, r in self.records.items()
                if r.get('receipt') and k.split('\\', 1)[-1] == comp}
