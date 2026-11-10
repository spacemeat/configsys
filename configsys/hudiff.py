'''hudiff.py — what changed in a `.hu` file, in plain words by key path: the Plugins review's
summaries (review.py; the raw unified diff stays one key away).

The two versions are read as data — the same reading `humerge` merges — and compared key by key, so a
comment, a re-wrapped list or a moved line is no change at all, and what is left reads as a sentence:

- a setting: `splash: plain → braille-bar`, `added splash: plain`, `removed splash (was plain)`;
- a nested map, by dotted path: `components.htop.standing: 1 → 2`, `components.htop.description
  changed` (a long value isn't spelled out), `added components.btop`;
- an order-free name list (humerge.SET_LISTS — a picks column, `disabled-drivers:`, …) by what came
  and went: `picks: laptop + ripgrep − btop` (its order means nothing, so a reorder is no change); an
  ordered one (a profile's terms) the same, or `profiles: dev reordered`;
- the `plugins:` list per source, by plugin name: `configsys-source: ref v0.1.12 → v0.1.13`,
  `added plugin configsys-foo @v1`, `removed plugin configsys-bar`, `plugins: order changed`;
- a component's `install:` bindings per method: `components.htop.install: added via flatpak`,
  `components.htop.install[native]: added name: htop-ng`.

`summarize(old, new)` returns [(kind, text)] with kind 'add' | 'del' | 'change' — `[]` when the data is
the same (comments or layout only), None when a side isn't a readable humon map (the review then
says what happened to the file in one line; its diff is in the raw view).
'''

from typing import NamedTuple

from .humerge import GONE, SET_LISTS, Unmergeable, _load, _matches, _scalars

MOST = 40                                             # lines per file; the rest is counted
_LONG = 40                                            # a value longer than this isn't spelled out


class Line(NamedTuple):
    kind: str                                         # 'add' | 'del' | 'change'
    text: str


def summarize(old_text, new_text):
    '''The plain-language changes from `old_text` to `new_text` (None = the file doesn't exist on that
    side), or None when either doesn't read as a humon map.'''
    try:
        a = _load(old_text or '')
        b = _load(new_text or '')
    except Unmergeable:
        return None
    out = []
    _walk((), a, b, out, None)
    if len(out) > MOST:
        out = out[:MOST] + [Line('change', f'… and {len(out) - MOST} more changes')]
    return out


def _dotted(path):
    s = ''
    for p in path:
        s += p if (not s or p.startswith('[')) else f'.{p}'
    return s


def _short(v):
    '''`v` as a few words, or None when it is too long (or not a plain value) to spell out.'''
    if isinstance(v, (dict, list)):
        return None
    v = str(v)
    if v.startswith('sha256:') and len(v) > 19:       # a content hash: its head says which
        return v[:19] + '…'
    return v if len(v) <= _LONG and '\n' not in v else None


class _Out:
    '''Phrases one change, inside an entry (a plugin, a binding: `<entry>: …`) or not.'''

    def __init__(self, out, entry):
        self.out, self.entry = out, entry

    def put(self, kind, text):
        self.out.append(Line(kind, f'{self.entry}: {text}' if self.entry else text))

    def changed(self, where, a, b):
        sa, sb = _short(a), _short(b)
        if sa is None or sb is None:
            self.put('change', f'{where} changed')
        else:
            self.put('change', f'{where} {sa} → {sb}' if self.entry else f'{where}: {sa} → {sb}')

    def added(self, where, v):
        s = _short(v)
        self.put('add', f'added {where}' + (f': {s}' if s is not None else ''))

    def removed(self, where, v):
        s = _short(v)
        self.put('del', f'removed {where}' + (f' (was {s})' if s is not None else ''))


def _walk(path, a, b, out, entry, rel=()):
    '''Append the changes from `a` to `b` at `path` (the full key path, for SET_LISTS) — `rel` is the
    part shown inside an `entry`.'''
    if a == b:
        return
    say = _Out(out, entry)
    where = _dotted(rel if entry else path)
    if isinstance(a, dict) and isinstance(b, dict):
        for k in b:
            _walk(path + (k,), a.get(k, GONE), b[k], out, entry, rel + (k,))
        for k in a:
            if k not in b:
                _walk(path + (k,), a[k], GONE, out, entry, rel + (k,))
        return
    if a is GONE or b is GONE:
        v = b if a is GONE else a
        if isinstance(v, list) and _plugin_list(path, v):
            _plugins(path, [] if a is GONE else a, [] if b is GONE else b, out)
        elif isinstance(v, list) and _binding_list(v):
            _bindings(path, [] if a is GONE else a, [] if b is GONE else b, out)
        elif _scalars(v) and isinstance(v, list):
            _names(path, [] if a is GONE else a, [] if b is GONE else b, out, entry, rel)
        elif isinstance(v, dict) and v and _matches(path + ('*',), SET_LISTS):
            for k in v:                               # a new picks map: per column
                _walk(path + (k,), GONE if a is GONE else v[k], v[k] if a is GONE else GONE, out, entry,
                      rel + (k,))
        elif isinstance(v, dict) and len(path) == 1 and not entry:
            names = list(v)
            shown = ', '.join(names[:6]) + (f' … ({len(names)})' if len(names) > 6 else '')
            say.put('add' if a is GONE else 'del', f'{"added" if a is GONE else "removed"} {where}'
                                                   + (f': {shown}' if names else ''))
        elif a is GONE:
            say.added(where, v)
        else:
            say.removed(where, v)
        return
    if isinstance(a, list) and isinstance(b, list):
        if _plugin_list(path, a) and _plugin_list(path, b):
            _plugins(path, a, b, out)
        elif _binding_list(a) and _binding_list(b):
            _bindings(path, a, b, out)
        elif _scalars(a) and _scalars(b):
            _names(path, a, b, out, entry, rel)
        else:
            say.put('change', f'{where}: {len(a)} → {len(b)} entries' if len(a) != len(b)
                    else f'{where} changed')
        return
    say.changed(where, a, b)


def _names(path, a, b, out, entry, rel):
    '''A list of names: what came (+) and went (−); a reorder only where order means something.'''
    shown = rel if entry else path
    label = f'{_dotted(shown[:-1])}: {shown[-1]}' if len(shown) > 1 else f'{shown[0]}:'
    came = [x for x in b if x not in a]
    went = [x for x in a if x not in b]
    say = _Out(out, entry)
    if came or went:
        kind = 'change' if came and went else 'add' if came else 'del'
        say.put(kind, label + ''.join(f' + {x}' for x in came) + ''.join(f' − {x}' for x in went))
    elif not _matches(path, SET_LISTS) and [x for x in a if x in b] != [x for x in b if x in a]:
        say.put('change', f'{label} reordered')


def _plugin_list(path, v):
    return path[-1:] == ('plugins',) and all(isinstance(d, dict) and d.get('source') for d in v)


def _plugins(path, a, b, out):
    '''`plugins:` per source, by name (a source change keeps the name: `x: source a → b`).'''
    from .plugins import dir_name
    ka = {str(d['source']): d for d in a}
    kb = {str(d['source']): d for d in b}
    if len(ka) != len(a) or len(kb) != len(b):        # a source declared twice: no per-source view
        out.append(Line('change', f'{_dotted(path)} changed'))
        return
    gone = {dir_name(s): s for s in ka if s not in kb}
    renamed = {s: gone[dir_name(s)] for s in kb if s not in ka and dir_name(s) in gone}
    for src, d in kb.items():
        name = dir_name(src)
        old = ka.get(src) or ka.get(renamed.get(src))
        if old is None:
            ref = d.get('ref')
            out.append(Line('add', f'added plugin {name}' + (f' @{ref}' if ref else '')))
        else:
            _walk(path + (src,), old, d, out, name)
    for src in ka:
        if src not in kb and src not in renamed.values():
            out.append(Line('del', f'removed plugin {dir_name(src)}'))
    shared = [s for s in kb if s in ka]
    if [s for s in ka if s in shared] != shared:
        out.append(Line('change', f'{_dotted(path)}: order changed (later = higher precedence)'))


def _binding_list(v):
    return bool(v) and all(isinstance(d, dict) and d.get('via') for d in v)


def _bindings(path, a, b, out):
    '''A component's `install:` per method — a binding is its (via, when).'''
    ident = lambda d: (str(d['via']), d.get('when'))  # noqa: E731
    ka, kb = {ident(d): d for d in a}, {ident(d): d for d in b}
    where = _dotted(path)
    if len(ka) != len(a) or len(kb) != len(b):        # two bindings alike: no per-method view
        out.append(Line('change', f'{where} changed'))
        return

    def label(k):
        via, when = k
        return f'via {via}' + (f' when {when}' if when else '')
    for k, d in kb.items():
        if k not in ka:
            out.append(Line('add', f'{where}: added {label(k)}'))
        else:                                         # changed in place: `<where>[via]: …`
            tag = f'[{k[0]}' + (f' when {k[1]}' if k[1] else '') + ']'
            _walk(path + (tag,), ka[k], d, out, where + tag)
    for k in ka:
        if k not in kb:
            out.append(Line('del', f'{where}: removed {label(k)}'))
