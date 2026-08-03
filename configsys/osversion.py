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
        clauses.append((m.group(1) or '=', parse_version(m.group(2))))
    return clauses or None


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
