'''terminfo.py — read and write ncurses' compiled terminfo format, in pure Python.

Just enough to derive a direct-color (`-direct`) entry from the terminal's own entry when the
system has neither a `-direct` entry (those ship in `ncurses-term`) nor `tic` to compile one — the
common case in minimal containers. screen.py tries `tic` first; this is the no-tic fallback.

The format (term(5)): a 12-byte header, the names, the standard booleans / numbers / string
offsets / string table, then an optional EXTENDED section (user-defined caps like RGB, AX, kUP5)
with its own header, values, and the capability NAMES stored after the extended string values.
Numbers are 16-bit in the legacy format (magic 0o432) and 32-bit in ncurses 6.1+'s (magic
0o1036) — direct color needs the latter (colors#0x1000000 doesn't fit in 16 bits).
'''

import os
import struct

MAGIC_16, MAGIC_32 = 0o432, 0o1036
ABSENT, CANCELLED = -1, -2

# Standard capability indices — fixed by the SVr4 terminfo layout (term.h), the same everywhere.
B_CCC = 27                                  # can_change
N_COLORS, N_PAIRS = 13, 14                  # max_colors, max_pairs
S_OP, S_INITC, S_SETF, S_SETB, S_SETAF, S_SETAB = 297, 299, 302, 303, 359, 360

# ncurses' own `xterm+direct` building block (the colon-form 24-bit SGR; indices < 8 stay ANSI).
DIRECT_SETAF = (b'\x1b[%?%p1%{8}%<%t3%p1%d%e38:2::%p1%{65536}%/%d:%p1%{256}%/%{255}%&%d:'
                b'%p1%{255}%&%d%;m')
DIRECT_SETAB = (b'\x1b[%?%p1%{8}%<%t4%p1%d%e48:2::%p1%{65536}%/%d:%p1%{256}%/%{255}%&%d:'
                b'%p1%{255}%&%d%;m')


class Entry:
    '''A decoded compiled entry. Standard caps are positional lists (bools: 0/1; numbers: int or
    ABSENT/CANCELLED; strings: bytes or ABSENT/CANCELLED); extended caps are ordered name->value
    dicts per type, same value conventions.'''

    def __init__(self, names, bools, nums, strs, ext_bools, ext_nums, ext_strs):
        self.names = names
        self.bools, self.nums, self.strs = bools, nums, strs
        self.ext_bools, self.ext_nums, self.ext_strs = ext_bools, ext_nums, ext_strs


class _Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, n):
        if self.pos + n > len(self.data):
            raise ValueError('truncated terminfo entry')
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def shorts(self, n):
        return list(struct.unpack(f'<{n}h', self.take(2 * n))) if n else []

    def numbers(self, n, wide):
        return list(struct.unpack(f'<{n}{"i" if wide else "h"}', self.take((4 if wide else 2) * n))) if n else []

    def even(self):
        if self.pos % 2:
            self.pos += 1

    @property
    def remaining(self):
        return len(self.data) - self.pos


def _cstr(table, off):
    end = table.index(b'\0', off)
    return table[off:end]


def _strings(offsets, table):
    return [o if o < 0 else _cstr(table, o) for o in offsets]


def parse(data):
    r = _Reader(data)
    magic, name_size, nbool, nnum, nstr, str_size = r.shorts(6)
    if magic not in (MAGIC_16, MAGIC_32):
        raise ValueError(f'not a compiled terminfo entry (magic {magic:#o})')
    wide = magic == MAGIC_32
    names = r.take(name_size).rstrip(b'\0')
    bools = list(r.take(nbool))
    r.even()
    nums = r.numbers(nnum, wide)
    offs = r.shorts(nstr)
    strs = _strings(offs, r.take(str_size))
    ext_bools, ext_nums, ext_strs = {}, {}, {}
    r.even()
    if r.remaining >= 10:
        xb, xn, xs, _count, xsize = r.shorts(5)
        bvals = list(r.take(xb))
        r.even()
        nvals = r.numbers(xn, wide)
        voffs = r.shorts(xs)
        noffs = r.shorts(xb + xn + xs)
        table = r.take(xsize)
        svals = _strings(voffs, table)
        # the capability NAMES follow the last string value; their offsets count from there
        base = max([o + len(_cstr(table, o)) + 1 for o in voffs if o >= 0], default=0)
        cap_names = [_cstr(table, base + o).decode('ascii') for o in noffs]
        ext_bools = dict(zip(cap_names[:xb], bvals))
        ext_nums = dict(zip(cap_names[xb:xb + xn], nvals))
        ext_strs = dict(zip(cap_names[xb + xn:], svals))
    return Entry(names, bools, nums, strs, ext_bools, ext_nums, ext_strs)


def _pack_strings(values):
    '''(offsets, table) for a list of bytes / ABSENT / CANCELLED values.'''
    offs, table = [], bytearray()
    for v in values:
        if isinstance(v, int):
            offs.append(v)
        else:
            offs.append(len(table))
            table += v + b'\0'
    return offs, bytes(table)


def serialize(e, wide=True):
    numfmt = 'i' if wide else 'h'
    out = bytearray()
    names = e.names + b'\0'
    soffs, stable = _pack_strings(e.strs)
    out += struct.pack('<6h', MAGIC_32 if wide else MAGIC_16, len(names), len(e.bools), len(e.nums),
                       len(soffs), len(stable))
    out += names + bytes(e.bools)
    if len(out) % 2:
        out += b'\0'
    out += struct.pack(f'<{len(e.nums)}{numfmt}', *e.nums)
    out += struct.pack(f'<{len(soffs)}h', *soffs) + stable
    if not (e.ext_bools or e.ext_nums or e.ext_strs):
        return bytes(out)
    if len(out) % 2:
        out += b'\0'
    voffs, vtable = _pack_strings(list(e.ext_strs.values()))
    cap_names = list(e.ext_bools) + list(e.ext_nums) + list(e.ext_strs)
    noffs, ntable = _pack_strings([n.encode('ascii') for n in cap_names])
    count = sum(1 for o in voffs if o >= 0) + len(cap_names)
    out += struct.pack('<5h', len(e.ext_bools), len(e.ext_nums), len(e.ext_strs), count,
                       len(vtable) + len(ntable))
    out += bytes(e.ext_bools.values())
    if len(e.ext_bools) % 2:
        out += b'\0'
    out += struct.pack(f'<{len(e.ext_nums)}{numfmt}', *e.ext_nums.values())
    out += struct.pack(f'<{len(voffs) + len(noffs)}h', *voffs, *noffs)
    out += vtable + ntable
    return bytes(out)


def _set(lst, i, v, fill):
    if i >= len(lst):
        lst.extend([fill] * (i + 1 - len(lst)))
    lst[i] = v


def make_direct(e, name, term):
    '''A copy of entry `e` as the direct-color `name` — the same overlay screen.py hands `tic`
    (ncurses' xterm+direct over `use=term`).'''
    d = Entry(f'{name}|{term} with direct color (built by configsys)'.encode('ascii'),
              list(e.bools), list(e.nums), list(e.strs),
              dict(e.ext_bools), dict(e.ext_nums), dict(e.ext_strs))
    _set(d.bools, B_CCC, 0, 0)
    _set(d.nums, N_COLORS, 0x1000000, ABSENT)
    _set(d.nums, N_PAIRS, 0x10000, ABSENT)
    for i in (S_INITC, S_SETF, S_SETB):
        _set(d.strs, i, CANCELLED, ABSENT)
    _set(d.strs, S_OP, b'\x1b[39;49m', ABSENT)
    _set(d.strs, S_SETAF, DIRECT_SETAF, ABSENT)
    _set(d.strs, S_SETAB, DIRECT_SETAB, ABSENT)
    d.ext_bools['RGB'] = 1
    d.ext_nums['CO'] = 8
    # tic keeps each type's extended names sorted; readers that pair caps by position (infocmp -d)
    # get confused otherwise
    d.ext_bools, d.ext_nums, d.ext_strs = (dict(sorted(x.items())) for x in (d.ext_bools, d.ext_nums, d.ext_strs))
    return d


def entry_path(root, name):
    return os.path.join(root, name[0], name)


def find_compiled(name, dirs):
    '''The compiled file for `name` in the first of `dirs` holding it (Linux or macOS hex layout).'''
    for d in filter(None, dirs):
        for sub in (name[0], f'{ord(name[0]):x}'):
            p = os.path.join(d, sub, name)
            if os.path.isfile(p):
                return p
    return None


def build_direct(name, term, dirs, out):
    '''Write `name` (the direct-color variant of `term`, found in `dirs`) under terminfo dir `out`.
    True on success; False if `term`'s entry can't be found or read.'''
    src = find_compiled(term, dirs)
    if not src:
        return False
    try:
        with open(src, 'rb') as f:
            base = parse(f.read())
        data = serialize(make_direct(base, name, term), wide=True)
        dest = entry_path(out, name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, dest)
    except (OSError, ValueError, struct.error):
        return False
    return True
