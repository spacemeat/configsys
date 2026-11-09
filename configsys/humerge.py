'''humerge.py — a three-way merge for `.hu` files that knows their structure (docs/done/
primary-push-plan.md, phase 4).

Git merges line by line, so two machines that each add a pick to their own `picks:` column touch
neighbouring lines and git calls it a conflict. Here the three versions (base, mine, theirs) are read
as data and merged key by key:

- a key only one side changed takes that side; both sides making the same change is no conflict;
- maps merge per key, all the way down (`picks:` per machine column, `components:` / `profiles:` /
  `pins:` per name, scalar settings per key);
- order-free name lists (a picks column, `disabled-drivers:`, …) changed on both sides take both
  sides' additions and both sides' removals;
- a profile's terms are ORDERED (`+editors ~vim` ≠ `~vim +editors`): both sides' edits combine in
  place where they don't overlap, and both adding at the same point keeps mine's then theirs';
  overlapping edits that differ are a conflict;
- `plugins:` entries merge per source; when both sides moved the same plugin to a different version,
  the newer one is kept and a note says so;
- anything else both sides changed differently is a CONFLICT: a `Conflict` says what each side did
  in plain words, and `merge(..., answers={path: 'mine' | 'theirs'})` settles it.

The merged text is built from MINE's text: every key whose value doesn't change keeps its text and
comments; a key taken whole from theirs is copied from theirs' text verbatim; a list combined from
both sides is edited in place (items removed and inserted, its comments kept); only a map entry
combined from both sides is written fresh. Theirs' text is taken whole only when this machine changed
nothing. The result is re-read and compared with the merged data, so a file this can't rewrite
faithfully raises `Unmergeable` (the caller falls back to asking about the whole file).

`main(argv)` — `NOTES BASE MINE THEIRS [PATH [MARKER_SIZE]]` — is git's merge driver: the result
goes to MINE, exit 0 when settled, 1 when a conflict is left. Then MINE holds what `git merge-file`
leaves (labelled markers, the file's own line endings); a file even git can't merge (binary) is left
untouched. A clean git line merge is kept as the result unless it differs from this merge only in a
name list's order or duplicates. `primarygit` runs it isolated (`python -I -c`, configsys's own path
— never a module from the primary's checkout) and registers it only for the length of its own rebase
/ merge (`git -c merge.configsys.driver=…`), so nothing is configured permanently.
'''

import subprocess
import sys
from difflib import SequenceMatcher

from .hutext import emit as _emit, key as _safe_key, scalar_end as _scalar_end, skip_blank as _skip

GONE = object()                                       # "this side has no such key"


class Unmergeable(Exception):
    '''Not a humon map, unreadable, or a shape this merge can't rewrite faithfully.'''


# Name lists whose order carries no meaning (a set of names): both sides' additions and removals
# combine. Path patterns, '*' = any one key. Profiles are NOT here — their order is meaning
# (ORDERED_LISTS).
SET_LISTS = (
    ('picks', '*'),
    ('disabled-drivers',),
    ('orphans-ignore',),
    ('installer-shell-writes-allow',),
    ('components', '*', 'attrs'),
)

# Lists whose order IS meaning (a profile's term algebra: a later `+x` re-adds what `~x` removed):
# merged as sequences, in order.
ORDERED_LISTS = (
    ('profiles', '*'),
)


class Conflict:
    '''Both sides changed `path` to different values.'''

    def __init__(self, path, base, mine, theirs):
        self.path, self.base, self.mine, self.theirs = path, base, mine, theirs

    @property
    def where(self):
        return ' › '.join(self.path) or 'the file'

    def words(self):
        '''"This machine set `splash: plain`; your other machine set `splash: ocean`."'''
        return f'This machine {_did(self.where, self.mine)}; your other machine {_did(self.where, self.theirs)}.'

    def __repr__(self):
        return f'Conflict({self.where})'


class Result:
    def __init__(self, text, merged, conflicts, notes):
        self.text, self.merged, self.conflicts, self.notes = text, merged, conflicts, notes


def _did(where, v):
    if v is GONE:
        return f'removed `{where}`'
    if isinstance(v, dict):
        return f'changed `{where}`'
    if isinstance(v, list):
        if all(not isinstance(x, (dict, list)) for x in v):
            body = '  '.join(str(x) for x in v)
            return f'set `{where}: [ {body if len(body) <= 60 else body[:57] + "…"} ]`'
        return f'changed `{where}`'
    return f'set `{where}: {v}`'


# -- the data merge --

def _load(text):
    from . import layers
    if not (text or '').strip():
        return {}
    try:
        data = layers.materialize_string(text)
    except Exception as e:                             # noqa: BLE001 — humon's error, unreadable
        raise Unmergeable(f'not readable humon: {e}')
    if not isinstance(data, dict):
        raise Unmergeable('not a humon map')
    return data


def _matches(path, patterns):
    return any(len(p) == len(path) and all(a in ('*', b) for a, b in zip(p, path)) for p in patterns)


def _set_like(path):
    return _matches(path, SET_LISTS)


def _merge_sequence(base, mine, theirs):
    '''A three-way merge of ordered lists (diff3 over items): each side's edits against base, applied
    where they don't overlap; both inserting at the same point keeps mine's then theirs' (theirs'
    duplicates dropped); identical edits apply once. None when edits overlap and differ.'''
    def ops(side, who):
        sm = SequenceMatcher(a=base, b=side, autojunk=False)
        return [(i1, i2, side[j1:j2], who) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != 'equal']
    edits = sorted(ops(mine, 'm') + ops(theirs, 't'), key=lambda o: (o[0], o[1]))
    groups = []
    for op in edits:
        if groups:
            g = groups[-1]
            gs, ge = min(o[0] for o in g), max(o[1] for o in g)
            same_point = op[0] == op[1] == gs == ge
            if op[0] < ge or same_point:
                g.append(op)
                continue
        groups.append([op])

    def apply(group, gs, ge, who):
        seg, pos = [], gs
        for i1, i2, rep_, w in group:
            if w == who:
                seg += base[pos:i1] + list(rep_)
                pos = i2
        return seg + base[pos:ge]

    out, pos = [], 0
    for g in groups:
        gs, ge = min(o[0] for o in g), max(o[1] for o in g)
        out += base[pos:gs]
        vm, vt = apply(g, gs, ge, 'm'), apply(g, gs, ge, 't')
        sides = {o[3] for o in g}
        if len(sides) == 1:
            out += vm if sides == {'m'} else vt
        elif vm == vt:
            out += vm
        elif gs == ge:                                 # both inserted at the same point
            out += vm + [x for x in vt if x not in vm]
        else:
            return None
        pos = ge
    return out + base[pos:]


def _scalars(v):
    return isinstance(v, list) and all(not isinstance(x, (dict, list)) for x in v)


def _same_but_ref(a, b):
    '''Two plugin entries that differ only in their ref (and the sha256 that goes with it).'''
    if not (isinstance(a, dict) and isinstance(b, dict)) or a.get('ref') == b.get('ref'):
        return False
    rest = lambda d: {k: v for k, v in d.items() if k not in ('ref', 'sha256')}
    return rest(a) == rest(b)


def _version(ref):
    from packaging.version import InvalidVersion, Version
    try:
        return Version(str(ref).lstrip('vV'))
    except (InvalidVersion, TypeError):
        return None


class _Merge:
    def __init__(self, answers):
        self.answers = answers or {}
        self.conflicts, self.notes = [], []

    def value(self, b, m, t, path):
        if m == t:
            return m
        if m == b:
            return t
        if t == b:
            return m
        if path in self.answers:
            return m if self.answers[path] == 'mine' else t
        if isinstance(m, dict) and isinstance(t, dict) and (b is GONE or isinstance(b, dict)):
            bb = b if isinstance(b, dict) else {}
            out = {}
            for k in list(m) + [k for k in t if k not in m]:
                v = self.value(bb.get(k, GONE), m.get(k, GONE), t.get(k, GONE), path + (k,))
                if v is not GONE:
                    out[k] = v
            return out
        if path == ('plugins',) and isinstance(m, list) and isinstance(t, list):
            got = self.plugins(b if isinstance(b, list) else [], m, t, path)
            if got is not None:
                return got
        if _set_like(path) and _scalars(m) and _scalars(t) and (b is GONE or _scalars(b)):
            bb = b if isinstance(b, list) else []
            dropped = {x for x in bb if x not in t}
            return [x for x in m if x not in dropped] + [x for x in t if x not in bb and x not in m]
        if _matches(path, ORDERED_LISTS) and _scalars(m) and _scalars(t) and (b is GONE or _scalars(b)):
            bb = b if isinstance(b, list) else []
            shared = set(bb) & set(m) & set(t)
            rb, rm, rt = ([x for x in seq if x in shared] for seq in (bb, m, t))
            if not (rm != rb and rt != rb and rm != rt):   # both reordering differently: asked
                got = _merge_sequence(bb, m, t)
                if got is not None:
                    return got
        self.conflicts.append(Conflict(path, b, m, t))
        return m

    def plugins(self, b, m, t, path):
        '''`plugins:` per entry, by source. None when an entry has no source (a conflict, then). The
        list's ORDER is plugin layer precedence: one side's reordering is kept; both reordering the
        same plugins differently is asked. A source declared twice is Unmergeable.'''
        def keyed(lst):
            if not all(isinstance(d, dict) and isinstance(d.get('source'), str) and d['source']
                       for d in lst):
                return None
            sources = [d['source'] for d in lst]
            if len(set(sources)) != len(sources):
                raise Unmergeable('a plugin source is declared twice')
            return {d['source']: d for d in lst}
        bk, mk, tk = keyed(b), keyed(m), keyed(t)
        if bk is None or mk is None or tk is None:
            return None
        shared = [s for s in bk if s in mk and s in tk]
        rel = lambda keys: [s for s in keys if s in shared]          # noqa: E731
        rb, rm, rt = rel(bk), rel(mk), rel(tk)
        if rm != rb and rt != rb and rm != rt:          # both reordered, differently: ask
            self.conflicts.append(Conflict(path, b, m, t))
            return m
        first, second = (list(tk), list(mk)) if (rt != rb and rm == rb) else (list(mk), list(tk))
        out = []
        for src in first + [s for s in second if s not in first]:
            bv, mv, tv = bk.get(src, GONE), mk.get(src, GONE), tk.get(src, GONE)
            p = path + (src,)
            if p not in self.answers and bv not in (mv, tv) and _same_but_ref(mv, tv):
                vm, vt = _version(mv.get('ref')), _version(tv.get('ref'))
                if vm is not None and vt is not None and vm != vt:
                    v = mv if vm > vt else tv
                    self.notes.append(f'both machines moved plugin {src} — kept the newer, {v["ref"]}.')
                    out.append(v)
                    continue
            v = self.value(bv, mv, tv, p)
            if v is not GONE:
                out.append(v)
        return out


def merge_data(base, mine, theirs, answers=None):
    '''(merged, conflicts, notes) for three humon maps. An unanswered conflict keeps mine's value.'''
    mg = _Merge(answers)
    merged = mg.value(base, mine, theirs, ())
    return merged, mg.conflicts, mg.notes


def merge(base_text, mine_text, theirs_text, answers=None):
    '''Three-way merge of three `.hu` texts -> Result. `.text` is None while conflicts remain
    unanswered. Raises Unmergeable when a text isn't a humon map or can't be rewritten faithfully.'''
    b, m, t = _load(base_text), _load(mine_text), _load(theirs_text)
    merged, conflicts, notes = merge_data(b, m, t, answers)
    if conflicts:
        return Result(None, merged, conflicts, notes)
    if merged == m:
        return Result(mine_text, merged, [], notes)
    if merged == t and mine_text == base_text:         # this machine changed nothing, not even a comment
        return Result(theirs_text, merged, [], notes)
    text = _rewrite(mine_text, m, theirs_text, t, merged, 0)
    if _load(text) != merged:
        raise Unmergeable('the combined file did not read back the same')
    return Result(text, merged, [], notes)


# -- building the merged text from mine's --

def _bounds(text):
    '''(open, close) indices of the `{ … }` map that `text` holds (leading comments allowed).'''
    from .hutext import value_end as _scan_value_end
    o = _skip(text, 0)
    if o >= len(text) or text[o] != '{':
        raise Unmergeable('not a map')
    return o, _scan_value_end(text, o) - 1


def _key(text, k):
    '''(key_start, value_start, value_end) of `k:` directly inside the map `text`, or None.'''
    from .hutext import section_span as _locate_section_span
    span = _locate_section_span(text, k)
    if span is None:
        return None
    start, end = span
    colon = text.index(':', start + len(k))
    vs = _skip(text, colon + 1)                         # (section_span ends a scalar at its token)
    return start, vs, end


def _indent_at(text, i):
    ls = text.rfind('\n', 0, i) + 1
    return i - ls


def _emit_kv(k, v, indent, top):
    if top and k == 'plugins' and isinstance(v, list) and all(isinstance(d, dict) for d in v):
        from .plugins import _emit_block
        return _emit_block(v, indent)
    return f'{_safe_key(k)}: {_emit(v, indent)}'


def _remove(text, k):
    found = _key(text, k)
    if found is None:
        raise Unmergeable(f'could not find `{k}`')
    start, _vs, end = found
    ls = text.rfind('\n', 0, start) + 1
    le = text.find('\n', end)
    le = len(text) if le < 0 else le
    if not text[ls:start].strip() and not text[end:le].strip():
        return text[:ls] + text[le + 1:]                # the key had its line to itself
    while start > 0 and text[start - 1] in ' \t':
        start -= 1
    return text[:start] + text[end:]


def _insert(text, piece):
    o, c = _bounds(text)
    ls = text.rfind('\n', 0, c) + 1
    if ls > o and not text[ls:c].strip():               # the close brace has its own line
        pad = ' ' * ((c - ls) + 4)
        return text[:ls] + pad + piece + '\n' + text[ls:]
    head = text[:c].rstrip()
    return head + ('  ' if head[-1] != '{' else ' ') + piece + ' ' + text[c:]


def _list_items(text):
    '''[(value, start, end)] for each scalar item of the `[ … ]` starting at text[0] (comments and
    separators between them skipped).'''
    out, i, n = [], 1, len(text)
    while True:
        i = _skip(text, i)
        if i >= n:
            raise Unmergeable('an unclosed list')
        if text[i] == ']':
            return out
        if text[i] == ',':
            i += 1
            continue
        if text[i] in '{[':
            raise Unmergeable('a list holding maps or lists')
        if text[i] == '@':                             # a metatag (`btop @why: work`): not a plain list
            raise Unmergeable('a list holding metatags')
        j = _scalar_end(text, i)
        if j <= i:                                     # never loop on a token the scanner can't read (B6)
            raise Unmergeable(f'an unreadable list item at {text[i:i + 12]!r}')
        tok = text[i:j]
        val = tok[1:-1] if len(tok) >= 2 and tok[0] in '"\'`' and tok[-1] == tok[0] else tok
        out.append((val, i, j))
        i = j


def _relist(text, old, new):
    '''The list text `text` (holding `old`) edited in place to hold `new`: items that left are cut
    out, items that came in are inserted beside their neighbours — every comment and line in it
    stays.'''
    from .hutext import scalar as _scalar
    items = _list_items(text)
    if [v for v, _s, _e in items] != [str(x) for x in old]:
        raise Unmergeable('a list that does not read the way it parses')
    sm = SequenceMatcher(a=[str(x) for x in old], b=[str(x) for x in new], autojunk=False)
    for tag, i1, i2, j1, j2 in reversed(sm.get_opcodes()):
        if tag == 'equal':
            continue
        for k in reversed(range(i1, i2)):                # cut, with the blanks after it on its line
            _v, s, e = items[k]
            while e < len(text) and text[e] in ' \t':
                e += 1
            text = text[:s] + text[e:]
        if j1 < j2:
            add = '  '.join(_scalar(x) for x in new[j1:j2])
            if i1 < i2:
                at = items[i1][1]
                text = text[:at] + add + '  ' + text[at:]
            elif i1 > 0:
                at = items[i1 - 1][2]
                text = text[:at] + '  ' + add + text[at:]
            else:
                text = text[:1] + ' ' + add + ('  ' if items else ' ') + text[1:].lstrip(' ')
    return text


def _rewrite(text, m, t_text, t, merged, depth):
    '''`text` (mine's map) rewritten to hold `merged`; t_text/t is theirs' map, or None.'''
    for k in [k for k in m if k not in merged]:
        text = _remove(text, k)
    for k, nv in merged.items():
        mv = m.get(k, GONE)
        if mv == nv:
            continue
        tv = t.get(k, GONE) if isinstance(t, dict) else GONE
        tspan = _key(t_text, k) if (t_text is not None and tv is not GONE) else None
        if mv is GONE:
            if tv == nv and tspan:
                piece = t_text[tspan[0]:tspan[2]]
            else:
                o, c = _bounds(text)
                piece = _emit_kv(k, nv, _indent_at(text, c) + 4, depth == 0)
            text = _insert(text, piece)
            continue
        found = _key(text, k)
        if found is None:
            raise Unmergeable(f'could not find `{k}`')
        start, vs, end = found
        if tv == nv and tspan:
            piece = t_text[tspan[0]:tspan[2]]
        elif _scalars(mv) and _scalars(nv) and text[vs:vs + 1] == '[':
            piece = text[start:vs] + _relist(text[vs:end], mv, nv)
        elif isinstance(mv, dict) and isinstance(nv, dict) and text[vs:vs + 1] == '{':
            sub_t = t_text[tspan[1]:tspan[2]] if (tspan and isinstance(tv, dict)
                                                 and t_text[tspan[1]:tspan[1] + 1] == '{') else None
            piece = text[start:vs] + _rewrite(text[vs:end], mv, sub_t, tv if sub_t is not None else None,
                                              nv, depth + 1)
        else:
            piece = _emit_kv(k, nv, _indent_at(text, start), depth == 0)
        text = text[:start] + piece + text[end:]
    return text


# -- the git merge driver --

def _line_merge(base, mine, theirs, marker_size=None):
    '''git's own line merge, as bytes: (rc, text). rc 0 = clean, 1..127 = conflicts left (markers
    labelled by machine), anything else = merge-file couldn't (a binary file) and the text is
    meaningless.'''
    argv = ['git', 'merge-file', '-p', '-L', 'this machine', '-L', 'base', '-L', 'your other machine']
    if marker_size and str(marker_size).isdigit():
        argv.append(f'--marker-size={marker_size}')
    r = subprocess.run(argv + [mine, base, theirs], capture_output=True)
    return r.returncode, r.stdout


def _as_sets(data, path=()):
    '''`data` with every order-free name list (SET_LISTS) as a set — to tell "git's clean merge only
    duplicated or reordered a pick" from a real difference.'''
    if isinstance(data, dict):
        return {k: _as_sets(v, path + (k,)) for k, v in data.items()}
    if isinstance(data, list) and _set_like(path) and _scalars(data):
        return frozenset(data)
    if isinstance(data, list):
        return [_as_sets(v, path) for v in data]
    return data


def _note(path, lines):
    if not path or path == '-' or not lines:
        return
    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(''.join(ln + '\n' for ln in lines))
    except OSError:
        pass


def driver(notes, base, mine, theirs, name='', marker_size=None):
    '''Merge driver body: the result into `mine`; 0 = settled, 1 = conflicts left (git's markers).
    What's worth telling you (a newer plugin kept, a file combined key by key) is appended to the
    file `notes` ('-' = nowhere). Never worse than git's own merge: when humerge can't settle it, `mine`
    gets exactly what `git merge-file` would leave — labelled markers, the file's own line endings —
    and when even git can't (a binary file), `mine` is left as it was and git sees a conflict.'''
    try:
        rc, lines = _line_merge(base, mine, theirs, marker_size)
    except Exception:                                  # noqa: BLE001 — no git: leave it to git
        return 1
    if rc < 0 or rc >= 128:                            # git couldn't merge it either: untouched
        return 1
    clean = rc == 0
    try:
        raw = [open(p, 'rb').read() for p in (base, mine, theirs)]
        crlf = b'\r\n' in raw[1]
        res = merge(*(b.decode('utf-8') for b in raw))
    except Exception:                                  # noqa: BLE001 — unreadable / not UTF-8: git's
        res = None
    if res is None or res.conflicts:
        with open(mine, 'wb') as f:
            f.write(lines)
        return 0 if clean else 1
    text = res.text
    if clean:                                          # git's own clean merge is the authority …
        try:
            gits = _load(lines.decode('utf-8'))
        except (Unmergeable, UnicodeDecodeError):
            gits = None
        if gits is not None and (gits == res.merged or _as_sets(gits) != _as_sets(res.merged)):
            with open(mine, 'wb') as f:                # … unless it differs only by a name list's
                f.write(lines)                         #   duplicates / order (both added one pick)
            _note(notes, res.notes)
            return 0
    if crlf:                                           # keep the file's own line ending
        text = text.replace('\r\n', '\n').replace('\n', '\r\n')
    with open(mine, 'wb') as f:
        f.write(text.encode('utf-8'))
    _note(notes, res.notes + ([f'{name or "a .hu file"}: both machines changed it — combined key by key.']
                       if not clean else []))
    return 0


def main(argv):
    '''The merge-driver entry point: `NOTES BASE MINE THEIRS [PATH [MARKER_SIZE]]` (git's
    `%O %A %B %P %L` after the notes file). The exit status for git.'''
    if not 4 <= len(argv) <= 6:
        print('usage: humerge NOTES BASE MINE THEIRS [PATH [MARKER_SIZE]]', file=sys.stderr)
        return 2
    return driver(*argv)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
