'''hutext.py — reading and editing humon as TEXT, so a write keeps every comment and line around it.

configsys edits your config files surgically: find a key's span in the text, replace just that, leave
the rest byte for byte (troveio parses; this never does). One scanner and one quoting rule for every
writer — plugins' section edits, troveio's ledger emit, humerge's merged files — so they agree on what
humon is: three quote styles (`"…"`, `'…'`, a backtick) with NO escape mechanism (a backslash is just
a backslash), `//` and `/* */` comments, and braces / brackets that only count outside those.
'''

# Characters that force a scalar to be quoted (humon would otherwise mis-tokenize).
UNSAFE = set(' \t\n\r{}[]:,"\'`\\@')


def scalar(v):
    '''A value as humon text: bare when safe, else in a quote style the value doesn't contain.'''
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if v is None:
        return '""'
    s = str(v)
    if s and not any(c in UNSAFE for c in s):
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


def key(k):
    '''A map key as humon text (quoted only when it has to be).'''
    return scalar(k) if (not k or any(c in UNSAFE for c in str(k))) else str(k)


def skip_trivia(text, i):
    '''Advance past ONE run of whitespace / `//` line comment / `/* */` block comment / quoted
    string starting at `i`; return the new index (unchanged if `i` is none of those). Humon
    honors both C++ (`//`) and C (`/* */`) comments, and braces/brackets can appear inside a
    comment or a `"..."`/`'...'` string — the span scanner must step over all of them so their
    contents never fool the depth counter. Humon quotes with `"`, `'` or a backtick, and has NO escape
    mechanism (a backslash is just a backslash), so a string runs to the next matching quote.'''
    n = len(text)
    c = text[i]
    if c in ' \t\r\n':
        while i < n and text[i] in ' \t\r\n':
            i += 1
        return i
    if c == '/' and i + 1 < n and text[i + 1] == '/':
        j = text.find('\n', i)
        return n if j < 0 else j
    if c == '/' and i + 1 < n and text[i + 1] == '*':
        j = text.find('*/', i + 2)
        return n if j < 0 else j + 2
    if c in '"\'`':
        j = text.find(c, i + 1)
        return n if j < 0 else j + 1
    return i


def value_end(text, i):
    '''End index (exclusive) of the humon value beginning at `i` (after `<key>:`). A `{...}`/`[...]`
    value brace-matches to its close (comment/string-aware); a bare scalar runs to end-of-line.'''
    n = len(text)
    while i < n:
        j = skip_trivia(text, i)
        if j != i:
            i = j
            continue
        break
    if i >= n:
        return n
    if text[i] in '{[':
        opens, closes = '{[', '}]'
        stack = [text[i]]
        i += 1
        while i < n and stack:
            j = skip_trivia(text, i)
            if j != i:
                i = j
                continue
            c = text[i]
            if c in opens:
                stack.append(c)
            elif c in closes:
                stack.pop()
            i += 1
        return i
    j = text.find('\n', i)                          # scalar value: to end of line
    return n if j < 0 else j


def section_span(text, section):
    '''(key_start, value_end) of a TOP-LEVEL `<section>: <value>` span — the key char through the
    end of its value — or None. Comment- and string-aware so braces inside `/* */`, `//`, or a
    quoted string never fool the depth counter, and it matches `section` only as a real key
    (depth 1, token-bounded, followed by `:`). This replaces the old humon-`source_text`-span
    approach, which mis-reported the span when humon bound a comment to the node (e.g. a trailing
    `/* */` before the closing brace), duplicating the section and dropping a brace.'''
    n, i, depth = len(text), 0, 0
    slen = len(section)
    while i < n:
        j = skip_trivia(text, i)
        if j != i:
            i = j
            continue
        c = text[i]
        if c in '{[':
            depth += 1
            i += 1
            continue
        if c in '}]':
            depth -= 1
            i += 1
            continue
        if (depth == 1 and text.startswith(section, i)
                and (i == 0 or text[i - 1] in ' \t\r\n{')      # left token boundary
                and i + slen <= n):
            k = i + slen
            while k < n and text[k] in ' \t':                  # ws before ':'
                k += 1
            if k < n and text[k] == ':':                       # a real `<section>:` key
                return i, value_end(text, k + 1)
        i += 1
    return None


def skip_blank(text, i):
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


def scalar_end(text, i):
    '''End of the scalar token at `i`: past its closing quote, or to the first delimiter / comment.'''
    q = text[i]
    if q in '"\'`':
        j = text.find(q, i + 1)
        return len(text) if j < 0 else j + 1
    j = i
    while j < len(text) and text[j] not in ' \t\r\n{}[]:,' and not text.startswith(('//', '/*'), j):
        j += 1
    return j


def emit(v, indent):
    '''Humon text for a value whose first line sits at `indent` (one-line name lists).'''
    pad, inner = ' ' * indent, ' ' * (indent + 4)
    if isinstance(v, dict):
        if not v:
            return '{}'
        return '\n'.join(['{'] + [f'{inner}{key(k)}: {emit(x, indent + 4)}' for k, x in v.items()]
                         + [pad + '}'])
    if isinstance(v, list):
        if not v:
            return '[]'
        if all(not isinstance(x, (dict, list)) for x in v):
            return '[ ' + '  '.join(scalar(x) for x in v) + ' ]'
        return '\n'.join(['['] + [f'{inner}{emit(x, indent + 4)}' for x in v] + [pad + ']'])
    return scalar(v)


