'''hutext.py — reading and editing humon as TEXT, so a write keeps every comment and line around it.

configsys edits your config files surgically: find a key's span in the text, replace just that, leave
the rest byte for byte (troveio parses; this never does). One scanner and one quoting rule for every
writer — plugins' section edits, troveio's ledger emit, humerge's merged files — so they agree on what
humon is: three quote styles (`"…"`, `'…'`, a backtick) with NO escape mechanism (a backslash is just
a backslash), `//` and `/* */` comments, and braces / brackets that only count outside those.
'''

# Characters that force a scalar to be quoted (humon would otherwise mis-tokenize).
UNSAFE = set(' \t\n\r{}[]:,"\'`\\@')
# ...and the two-character comment openers: humon starts a comment at `//` or `/*` even inside a
# bare word (`x//y` reads `x`), so a path with an empty `$VAR` in it must be quoted.
_COMMENT_OPENERS = ('//', '/*')


def _bare_ok(s):
    return bool(s) and not any(c in UNSAFE for c in s) and not any(o in s for o in _COMMENT_OPENERS)


def scalar(v):
    '''A value as humon text: bare when safe, else in a quote style the value doesn't contain.'''
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if v is None:
        return '""'
    s = str(v)
    if _bare_ok(s):
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
    return str(k) if _bare_ok(str(k)) else scalar(k)


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
    value brace-matches to its close (comment/string-aware); a scalar ends at its own token — past
    its closing quote, or at the first delimiter / comment — never at the end of the line, so a
    one-line map's later keys, a trailing comment and a root brace on the same line all survive.
    (Only blanks and comments are skipped first: a quoted string here IS the value.)'''
    n = len(text)
    i = skip_blank(text, i)
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
    return scalar_end(text, i)


def section_span(text, section):
    '''(key_start, value_end) of a TOP-LEVEL `<section>: <value>` span — the key char through the
    end of its value — or None. Comment- and string-aware so braces inside `/* */`, `//`, or a
    quoted string never fool the depth counter, and it matches `section` only as a real key: at
    depth 1, token-bounded (after whitespace, `{`, `,`, `]` or `}`), bare or quoted in any of humon's
    three styles (`"scope":`), followed by `:`. A key written TWICE yields the LAST copy — the one
    humon and layers.materialize read — so an edit changes what configsys sees. (This replaces the
    old humon-`source_text`-span approach, which mis-reported the span when humon bound a comment to
    the node, duplicating the section and dropping a brace.)'''
    n, i, depth = len(text), 0, 0
    slen = len(section)
    found = None
    while i < n:
        c = text[i]
        if depth == 1 and (i == 0 or text[i - 1] in _KEY_LEFT):
            k = _key_end(text, i, section, slen)
            if k is not None:
                while k < n and text[k] in ' \t':                  # ws before ':'
                    k += 1
                if k < n and text[k] == ':':                       # a real `<section>:` key
                    found = (i, value_end(text, k + 1))
                    i = found[1]                                   # keep looking: the last one wins
                    continue
        j = skip_trivia(text, i)
        if j != i:
            i = j
            continue
        if c in '{[':
            depth += 1
        elif c in '}]':
            depth -= 1
        i += 1
    return found


# What may sit just before a key: whitespace, the map's `{`, a `,` separator, or the close of the
# previous key's `[…]` / `{…}` value.
_KEY_LEFT = ' \t\r\n{,]}'


def _key_end(text, i, section, slen):
    '''The index just past `section` spelled as a key at `i` — bare (token-bounded on the right) or
    wrapped in one of humon's quotes — else None.'''
    q = text[i]
    if q in '"\'`':
        k = i + 1 + slen
        return k + 1 if text.startswith(section, i + 1) and text[k:k + 1] == q else None
    if not text.startswith(section, i):
        return None
    k = i + slen
    return k if k >= len(text) or text[k] in ' \t\r\n:' else None


def root_close(text):
    '''Index of the root map's closing `}` (the one that brings the depth back to 0), scanning
    comment- and string-aware; None when the document has no root map (empty, comment-only). The
    insert point for a new top-level key — never a `}` inside a trailing comment.'''
    n, i, depth, close = len(text), 0, 0, None
    while i < n:
        j = skip_trivia(text, i)
        if j != i:
            i = j
            continue
        c = text[i]
        if c in '{[':
            depth += 1
        elif c in '}]':
            depth -= 1
            if depth == 0 and c == '}':
                close = i
        i += 1
    return close


def remove_span(text, section):
    '''(start, end) to delete for a top-level `<section>:` — its exact key→value span, widened over
    the same-line whitespace before it and the blanks + one newline after it — or None. Located by
    section_span (never by searching for the node's text, which can also occur in a comment).'''
    span = section_span(text, section)
    if span is None:
        return None
    start, end = span
    while start > 0 and text[start - 1] in ' \t':
        start -= 1
    while end < len(text) and text[end] in ' \t':
        end += 1
    if end < len(text) and text[end] == '\n':
        end += 1
    return start, end


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


