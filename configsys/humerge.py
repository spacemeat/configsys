'''humerge.py — a three-way merge for `.hu` files that knows their structure (docs/done/
primary-push-plan.md, phase 4).

Git merges line by line, so two machines that each add a pick to their own `picks:` column touch
neighbouring lines and git calls it a conflict. Here the three versions (base, mine, theirs) are read
as data and merged key by key:

- a key only one side changed takes that side; both sides making the same change is no conflict;
- maps merge per key, all the way down (`picks:` per machine column, `components:` / `profiles:` /
  `pins:` per name, scalar settings per key);
- order-free name lists (a picks column, a profile's terms, `disabled-drivers:`, …) changed on both
  sides take both sides' additions and both sides' removals;
- `plugins:` entries merge per source; when both sides moved the same plugin to a different version,
  the newer one is kept and a note says so;
- anything else both sides changed differently is a CONFLICT: a `Conflict` says what each side did
  in plain words, and `merge(..., answers={path: 'mine' | 'theirs'})` settles it.

The merged text is built from MINE's text: every key whose value doesn't change keeps its text and
comments; a key taken whole from theirs is copied from theirs' text verbatim; only a key combined from
both sides is written fresh. The result is re-read and compared with the merged data, so a file this
can't rewrite faithfully raises `Unmergeable` (the caller falls back to asking about the whole file).

Run as `python -m configsys.humerge NOTES BASE MINE THEIRS [PATH]` it is a git merge driver: the result goes to
MINE, exit 0 when settled, 1 when a conflict is left (then MINE holds git's own conflict-marker text,
exactly what git's built-in merge would have left). It is never worse than git's merge: a file it
can't read, or a conflict git's line merge settles cleanly, gets git's own result. `primarygit` registers it only for the length of
its own rebase / merge (`git -c merge.configsys.driver=…`), so nothing is configured permanently.
'''

import subprocess
import sys

GONE = object()                                       # "this side has no such key"


class Unmergeable(Exception):
    '''Not a humon map, unreadable, or a shape this merge can't rewrite faithfully.'''


# Lists whose order carries no meaning: both sides' additions and removals combine. Path patterns,
# '*' = any one key.
SET_LISTS = (
    ('picks', '*'),
    ('profiles', '*'),
    ('disabled-drivers',),
    ('orphans-ignore',),
    ('installer-shell-writes-allow',),
    ('components', '*', 'attrs'),
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


def _set_like(path):
    return any(len(p) == len(path) and all(a in ('*', b) for a, b in zip(p, path)) for p in SET_LISTS)


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
        self.conflicts.append(Conflict(path, b, m, t))
        return m

    def plugins(self, b, m, t, path):
        '''`plugins:` per entry, by source. None when an entry has no source (a conflict, then).'''
        def keyed(lst):
            if not all(isinstance(d, dict) and d.get('source') for d in lst):
                return None
            return {d['source']: d for d in lst}
        bk, mk, tk = keyed(b), keyed(m), keyed(t)
        if bk is None or mk is None or tk is None:
            return None
        out = []
        for src in list(mk) + [s for s in tk if s not in mk]:
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
    if merged == t:
        return Result(theirs_text, merged, [], notes)
    text = _rewrite(mine_text, m, theirs_text, t, merged, 0)
    if _load(text) != merged:
        raise Unmergeable('the combined file did not read back the same')
    return Result(text, merged, [], notes)


# -- building the merged text from mine's --

def _skip(text, i):
    '''Past whitespace and comments (not strings — a quoted value is a value).'''
    n = len(text)
    while i < n:
        if text[i] in ' \t\r\n':
            i += 1
        elif text.startswith('//', i):
            j = text.find('\n', i)
            i = n if j < 0 else j + 1
        elif text.startswith('/*', i):
            j = text.find('*/', i + 2)
            i = n if j < 0 else j + 2
        else:
            break
    return i


def _bounds(text):
    '''(open, close) indices of the `{ … }` map that `text` holds (leading comments allowed).'''
    from .plugins import _scan_value_end
    o = _skip(text, 0)
    if o >= len(text) or text[o] != '{':
        raise Unmergeable('not a map')
    return o, _scan_value_end(text, o) - 1


def _key(text, k):
    '''(key_start, value_start, value_end) of `k:` directly inside the map `text`, or None.'''
    from .plugins import _locate_section_span
    span = _locate_section_span(text, k)
    if span is None:
        return None
    start, end = span
    colon = text.index(':', start + len(k))
    vs = _skip(text, colon + 1)
    if vs < len(text) and text[vs] not in '{[':         # a scalar ends at its token, not the line's
        end = _scalar_end(text, vs)                     #   end (a one-line map closes on that line)
    return start, vs, end


def _scalar_end(text, i):
    q = text[i]
    if q in '"\'`':
        j = text.find(q, i + 1)
        return len(text) if j < 0 else j + 1
    j = i
    while j < len(text) and text[j] not in ' \t\r\n{}[]:,' and not text.startswith(('//', '/*'), j):
        j += 1
    return j


def _indent_at(text, i):
    ls = text.rfind('\n', 0, i) + 1
    return i - ls


def _safe_key(k):
    from .troveio import _UNSAFE, _scalar
    return _scalar(k) if (not k or any(c in _UNSAFE for c in str(k))) else str(k)


def _emit(v, indent):
    '''Humon text for a value whose first line sits at `indent` (one-line name lists).'''
    from .troveio import _scalar
    pad, inner = ' ' * indent, ' ' * (indent + 4)
    if isinstance(v, dict):
        if not v:
            return '{}'
        return '\n'.join(['{'] + [f'{inner}{_safe_key(k)}: {_emit(x, indent + 4)}' for k, x in v.items()]
                         + [pad + '}'])
    if isinstance(v, list):
        if not v:
            return '[]'
        if _scalars(v):
            return '[ ' + '  '.join(_scalar(x) for x in v) + ' ]'
        return '\n'.join(['['] + [f'{inner}{_emit(x, indent + 4)}' for x in v] + [pad + ']'])
    return _scalar(v)


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

def _line_merge(base, mine, theirs):
    '''git's own line merge: (clean?, text with conflict markers where it isn't).'''
    r = subprocess.run(['git', 'merge-file', '-p', mine, base, theirs], capture_output=True, text=True)
    return r.returncode == 0, r.stdout


def _note(path, lines):
    if not path or path == '-' or not lines:
        return
    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(''.join(ln + '\n' for ln in lines))
    except OSError:
        pass


def driver(notes, base, mine, theirs, name=''):
    '''Merge driver body: the result into `mine`; 0 = settled, 1 = conflicts left (git's markers).
    What's worth telling you (a newer plugin kept, a file combined key by key) is appended to the
    file `notes` ('-' = nowhere).'''
    read = lambda p: open(p, encoding='utf-8').read()
    clean, lines = _line_merge(base, mine, theirs)
    try:
        res = merge(read(base), read(mine), read(theirs))
    except Exception:                                  # noqa: BLE001 — never worse than git's merge
        res = None
    if res is None or res.conflicts:
        with open(mine, 'w', encoding='utf-8') as f:
            f.write(lines)
        return 0 if clean else 1
    text = res.text
    if clean:                                          # git's merge reads the same: keep its text
        try:
            if _load(lines) == res.merged:
                text = lines
        except Unmergeable:
            pass
    with open(mine, 'w', encoding='utf-8') as f:
        f.write(text)
    _note(notes, res.notes + ([f'{name or "a .hu file"}: both machines changed it — combined key by key.']
                       if not clean else []))
    return 0


if __name__ == '__main__':
    sys.exit(driver(*sys.argv[1:6]))
