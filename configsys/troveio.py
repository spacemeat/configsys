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
# Key and scalar quoting are hutext's — one rule for every writer.
from .hutext import key as _key, scalar as _scalar

_INDENT = '    '


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


def _emit(obj, depth):
    pad = _INDENT * depth
    inner = _INDENT * (depth + 1)
    if isinstance(obj, dict):
        if not obj:
            return '{}'
        lines = ['{']
        for k, v in obj.items():
            key = _key(k)                     # (an empty or odd key is quoted, never `: v`)
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
