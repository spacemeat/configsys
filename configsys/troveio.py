'''troveio.py — humon I/O helpers.

Two jobs:
  * load(): parse a .hu file into a Trove, turning humon's DeserializeError into a
    friendly ConfigError. The caller MUST keep the returned Trove alive while it
    walks any Node from it (Nodes hold raw pointers into Trove memory).
  * emit_hu(): serialize a plain python dict/list/scalar back to Humon text. Troves
    are read-only, so ledger writes are produced this way (then written to disk).
'''

from pathlib import Path

import humon as h

from .errors import ConfigError

_INDENT = '    '

# Characters that force a scalar to be quoted (humon would otherwise mis-tokenize).
_UNSAFE = set(' \t\n\r{}[]:,"\'`\\@')


def load(path):
    '''Parse a .hu file -> Trove. Raises ConfigError on syntax errors / missing file.

    Reads the file as UTF-8 text and parses via from_string rather than
    humon.from_file: from_file sniffs the byte encoding and rejects very short
    files (e.g. a `{}` ledger) with BADENCODING. We always write UTF-8, and humon
    prefers UTF-8, so decoding here is both correct and more robust.
    '''
    try:
        text = Path(path).read_text(encoding='utf-8-sig')  # tolerate a BOM
    except FileNotFoundError:
        raise ConfigError(f'file not found: {path}')
    except UnicodeDecodeError as e:
        raise ConfigError(f'{path}: not valid UTF-8 ({e})')
    try:
        return load_string(text)
    except ConfigError as e:
        raise ConfigError(f'{path}: {e}')


def load_string(text):
    if not text.strip():
        raise ConfigError('empty humon document')
    try:
        return h.from_string(text)
    except h.DeserializeError as e:
        raise ConfigError(f'{e}')


def _scalar(v):
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if v is None:
        return '""'
    s = str(v)
    if s and not any(c in _UNSAFE for c in s):
        return s
    # Humon has no escapes; a delimiter that doesn't occur in the value works.
    if '"' not in s:
        return f'"{s}"'
    if "'" not in s:
        return f"'{s}'"
    if '`' not in s:
        return f'`{s}`'
    # Extremely unlikely for ledger data; fall back to backtick with backticks stripped.
    return '`' + s.replace('`', '') + '`'


def _emit(obj, depth):
    pad = _INDENT * depth
    inner = _INDENT * (depth + 1)
    if isinstance(obj, dict):
        if not obj:
            return '{}'
        lines = ['{']
        for k, v in obj.items():
            key = _scalar(k) if any(c in _UNSAFE for c in str(k)) else str(k)
            if isinstance(v, (dict, list)):
                lines.append(f'{inner}{key}: {_emit(v, depth + 1)}')
            else:
                lines.append(f'{inner}{key}: {_scalar(v)}')
        lines.append(f'{pad}}}')
        return '\n'.join(lines)
    if isinstance(obj, list):
        if not obj:
            return '[]'
        lines = ['[']
        for v in obj:
            if isinstance(v, (dict, list)):
                lines.append(f'{inner}{_emit(v, depth + 1)}')
            else:
                lines.append(f'{inner}{_scalar(v)}')
        lines.append(f'{pad}]')
        return '\n'.join(lines)
    return _scalar(obj)


def emit_hu(obj) -> str:
    '''Serialize a python dict/list/scalar to pretty Humon text (trailing newline).'''
    return _emit(obj, 0) + '\n'
