'''osversion.py — parse & compare the OS-version qualifiers on routes.hu blocks.

A block key may carry an `@`-qualifier that scopes it to a range of OS versions:

    "ubuntu@22.04"          exact VERSION_ID
    "ubuntu@<23.04"         everything below 23.04
    "ubuntu@>=24.04"        24.04 and up
    "ubuntu@>=20.04,<23.04" comma = AND (a bounded range)

Versions are the VERSION_ID from /etc/os-release (ubuntu "22.04", debian "12"),
parsed to int tuples so they order naturally.

Authoring pattern (keeps distro numberings from colliding across the cascade):
put the modern/default behavior in the bare base block and use `@<version`
variants for *older* exceptions. A constraint is compared against the one detected
VERSION_ID, so scope constraints to your target's numbering — e.g. ubuntu 22.04
never satisfies a `debian@<12` variant because (22,4) < (12,) is false.
'''

import re

_OP_RE = re.compile(r'^\s*(>=|<=|>|<|=)?\s*(.+?)\s*$')

_CMP = {
    '=':  lambda a, b: a == b,
    '<':  lambda a, b: a < b,
    '<=': lambda a, b: a <= b,
    '>':  lambda a, b: a > b,
    '>=': lambda a, b: a >= b,
}


def parse_version(s):
    '''"22.04" -> (22, 4); "12" -> (12,); None/garbage -> None.'''
    if s is None:
        return None
    if isinstance(s, tuple):
        return s
    parts = []
    for tok in str(s).strip().split('.'):
        m = re.match(r'\d+', tok)
        if not m:
            break
        parts.append(int(m.group(0)))
    return tuple(parts) if parts else None


_EPOCH = re.compile(r'^\d+:')   # a Debian epoch, e.g. `2:1.18~0ubuntu2`


def parse_loose(s):
    '''parse_version, normalized for comparing versions from DIFFERENT schemes — a distro package
    version against an upstream git tag. Strips a leading Debian epoch (`2:1.18…` -> `1.18…`, else
    it reads as 2.18) and a leading `v`/`V` (git tags); parse_version then takes each dotted token's
    leading digit run, so a Debian revision / packaging suffix (`-1`, `~0ubuntu2`) is dropped. So
    `v26.5.6` and `26.5.6-1` both parse to (26, 5, 6). None when unparseable.'''
    if s is None:
        return None
    s = _EPOCH.sub('', str(s).strip())
    if s[:1] in ('v', 'V') and s[1:2].isdigit():
        s = s[1:]
    return parse_version(s)


def clean_version(s):
    '''A DISPLAY-normalized version string: strip the packaging noise that makes the same upstream
    version look different across schemes (a Debian epoch `2:`, a leading `v`, a numeric Debian
    revision `-1`, a packaging suffix `~0ubuntu2`) so `v26.5.6` and `26.5.6-1` both show as `26.5.6`.
    Unlike parse_loose it keeps the STRING (and any pre-release tag like `-rc1`, which isn't a
    numeric revision). Returns the input unchanged if it doesn't start with a digit after stripping
    (nothing sensible to clean).'''
    if not s:
        return s
    t = _EPOCH.sub('', str(s).strip())
    if t[:1] in ('v', 'V') and t[1:2].isdigit():
        t = t[1:]
    # A `~` usually separates a real dotted upstream version from a packaging/pre-release suffix
    # (1.2.3~0ubuntu2 -> 1.2.3). But a `0~<snapshot>` scheme (e.g. abseil's 0~20210324.2, where a
    # date is packaged below a future 1.0) has NOTHING meaningful before the `~` — stripping it would
    # collapse the whole version to a bare "0". So only drop the `~`-suffix when the part before it is
    # a real dotted version; otherwise keep the snapshot.
    head = t.split('~', 1)[0]
    if '~' in t and '.' in head:
        t = head
    t = re.sub(r'-\d[^-]*$', '', t)     # Debian revision (-1, -1ubuntu1.12): it starts with a digit,
                                        # so a `-rc1` pre-release (starts with a letter) is kept
    return t if t[:1].isdigit() else s


def split_qualifier(block_key):
    '''"ubuntu@<23.04" -> ("ubuntu", "<23.04"); "ubuntu" -> ("ubuntu", None).'''
    base, sep, qual = block_key.partition('@')
    return (base, qual) if sep else (base, None)


def parse_constraint(text):
    '''"<23.04" -> [('<', (23,4))]; ">=20.04,<23.04" -> two clauses; None if empty.'''
    if not text or not text.strip():
        return None
    clauses = []
    for part in text.split(','):
        m = _OP_RE.match(part)
        if not m:
            continue
        operand = m.group(2).strip()
        if operand[:1] in ('v', 'V') and operand[1:2].isdigit():
            operand = operand[1:]                      # `>=v3.11` means 3.11
        clauses.append((m.group(1) or '=', parse_version(operand)))
    return clauses or None


def meets(version, constraint):
    '''Does version STRING `version` satisfy constraint TEXT `constraint` (`>=1.96`, `>1.0`, a bare
    `2.0` = exact, `,`-AND ranges)? Compared cross-scheme (parse_loose: a Debian epoch / leading `v`
    stripped). False when either is unparseable — an unverifiable floor is treated as NOT met
    (surfaced, not assumed ok). The one constraint check the floor subsystem uses.'''
    pv = parse_loose(version)
    clauses = parse_constraint(str(constraint)) if constraint is not None else None
    if pv is None or not clauses or any(target is None for _op, target in clauses):
        return False                                   # an unreadable operand abstains, never crashes (B4)
    return all(_CMP[op](pv, target) for op, target in clauses)


def _interval(clauses):
    '''(lo, lo_open, hi, hi_open) — the version range a parsed constraint admits (None = unbounded).'''
    lo = hi = None
    lo_open = hi_open = False
    for op, v in clauses:
        if op in ('=', '>=', '>') and (lo is None or v > lo or (v == lo and op == '>')):
            lo, lo_open = v, op == '>'
        if op in ('=', '<=', '<') and (hi is None or v < hi or (v == hi and op == '<')):
            hi, hi_open = v, op == '<'
    return lo, lo_open, hi, hi_open


def implies(promise, floor):
    '''Does every version satisfying constraint text `promise` satisfy `floor`? — a method's declared
    `provides: { cap: ">=9.4" }` meets a floor `>=9.2` but not `>=9.10`, and an upper bound `<9`
    guarantees no `>=8` at all. False when either is unparseable.'''
    pc, fc = parse_constraint(str(promise or '')), parse_constraint(str(floor or ''))
    if not pc or not fc or any(v is None for _op, v in pc + fc):
        return False
    plo, plo_open, phi, phi_open = _interval(pc)
    flo, flo_open, fhi, fhi_open = _interval(fc)
    if flo is not None and (plo is None or plo < flo or (plo == flo and flo_open and not plo_open)):
        return False
    if fhi is not None and (phi is None or phi > fhi or (phi == fhi and fhi_open and not phi_open)):
        return False
    return True


def satisfies(constraint, version):
    '''True if `version` (tuple) meets every clause of `constraint`.'''
    if version is None or not constraint:
        return False
    return all(ver is not None and _CMP[op](version, ver) for op, ver in constraint)


def specificity(constraint):
    '''Rank for picking among satisfied variants: exact > bounded range > open.'''
    if not constraint:
        return 0
    if len(constraint) == 1 and constraint[0][0] == '=':
        return 3               # exact pin (@22.04)
    if len(constraint) >= 2:
        return 2               # bounded range (@>=20.04,<23.04)
    return 1                   # single open comparator (@<23.04)
