---
name: humon-python
description: Read, navigate, and serialize Humon (.hu) data from Python using the Cython `humon` package. Use whenever code parses .hu files (routes.hu, config.hu, the user config, plugin data, the ledger), walks Humon nodes, reads metatags/annotations, or writes Humon back out.
---

# Using Humon from Python

[Humon](https://github.com/spacemeat/humon) is a human-oriented data format (JSON-family, but quotes and commas are optional and it supports comments + metatags). The Python binding is the Cython package [humon-cy](https://github.com/spacemeat/humon-cy), imported as `humon`.

## Setup — must use the project venv

The `humon` package is installed **only** in `.venv` (not system Python). Run everything through it:

```bash
.venv/bin/python your_script.py
```

The authoritative API reference is the Cython source shipped with the package:
`.venv/lib/python3.10/site-packages/humon/humon.pyx`. Read it when in doubt — the
GitHub README is partly stale (see "Stale README" below).

**In configsys, go through `configsys/troveio.py`** rather than calling humon directly:
`troveio.load(path)` / `load_string(text)` parse (turning `DeserializeError` into a friendly
`ConfigError`; `load` decodes UTF-8 itself and uses `from_string`, because `h.from_file` sniffs the
byte encoding and rejects very short files such as a `{}` ledger with `BADENCODING`), and
`troveio.emit_hu(obj)` serializes plain Python dicts/lists/scalars back to Humon text (troves are
read-only — see Serialization).

## Loading a trove

```python
import humon as h

trove = h.from_file('routes.hu')               # encoding=Encoding.UNKNOWN, tab_size=4
trove = h.from_string('{foo: [a b c]}')
```

Parse failures raise `humon.DeserializeError` (subclass of `humon.HumonError`). The
message embeds a list of `Error` objects (`.error_code`, `.line`, `.col`). Always be
ready to catch it — user-edited files (the user config, plugin data) can be malformed.

```python
try:
    trove = h.from_file('config.hu')
except h.DeserializeError as e:
    print(e)   # "Trove has syntax errors:\n[line 12, column 13: SYNTAXERROR, ...]"
```

## The data model

A `Trove` owns a tree of `Node`s. Every node has a `kind` (`NodeKind`):

- `DICT` — keyed children (order-preserving)
- `LIST` — indexed children
- `VALUE` — a leaf scalar
- `NULLNODE` — the null node returned for missing lookups

**All scalar values are strings.** `r['year'].value` on `year: 2024` returns the
string `'2024'` — the caller converts (`int(...)`, etc.).

## Navigation

Bracket access on a node (`__getitem__`):

```python
root = trove.root
root['skills']            # child by dict key       -> Node
root['jobs'][0]           # child by list index      -> Node
root['title', 1]          # Nth child with that key  -> Node  (for duplicate keys)
```

Duplicate keys are legal in Humon (e.g. two `title:` entries tagged with different
`@focus:` metatags). Use the `(key, n)` tuple form to disambiguate.

`get_node` takes an **address** (string) or, on a node, a relative address or child index:

```python
trove.get_node('/jobs/1/company')   # absolute address from trove
trove.get_node(3)                   # node by linear index (depth-first), not child index
node.get_node('../year')            # relative address from a node
node.get_node(0)                    # child by index from a node
```

Siblings:

```python
node.get_sibling()        # next sibling
node.get_sibling('bar')   # next sibling whose key is 'bar'
```

Missing lookups return **`None`** (not a null node) — guard accordingly:

```python
v = root['maybe_missing']
if v is not None:
    ...
```

Node introspection: `.key`, `.value`, `.kind`, `.parent`, `.num_children`,
`.node_index`, `.child_index`, `.address`, `.isnull`, `.source_text`.

### Iterating children

```python
jobs = root['experience']['professional']        # a LIST node
for i in range(jobs.num_children):
    job = jobs[i]
    print(job['company'].value)
```

For dict nodes, iterate by index too and read `.key` on each child.

## Keep the Trove alive while you use its Nodes

`Node` holds a raw pointer into the `Trove`'s memory and does **not** keep the trove
referenced. If the `Trove` is garbage-collected while you still hold `Node`s, the pointers
dangle and child lookups start silently returning `None` (no error). Always bind the trove
to a variable for as long as you walk it:

```python
trove = h.from_file('data.hu')   # GOOD: trove stays alive
result = walk(trove.root)

result = walk(h.from_file('data.hu').root)   # BUG: trove is freed mid-walk
```

## Unquoted multi-token values split

Whitespace separates list items and bare words don't include all characters, so unquoted
`C#` parses as two values (`C`, `#`) and `Drupal 7` as two list items. Quote them:
`'C#'`, `'Drupal 7'`.

## String quoting: `'…'`, `"…"`, and backtick `` `…` `` — all multiline, none escaped

A quoted scalar can use single quotes, double quotes, or **backticks**. Key facts (verified
against the installed parser, 0.1.0):

- **All quoted strings are multiline** — a newline inside the quotes is kept verbatim, and
  leading indentation on continuation lines is part of the value. (So if you indent a
  continuation line to line up with the config, those spaces land in the string.)
- **There is no escape mechanism.** `\"` is not an escape; a backslash is just a backslash.
  Only the *matching closing delimiter* ends the value — nothing else inside needs escaping.
- Therefore each quote style can contain the *other* quote characters freely:
  - `'…'` may contain `"` but not `'`
  - `"…"` may contain `'` but not `"`
  - `` `…` `` (backtick) may contain **both** `'` and `"` — only a backtick closes it.
- There is **no** heredoc / triple-quote syntax.

**Use a backtick string for any value that mixes quote characters** — e.g. a shell command with
both quote styles (a `script` binding's `install-cmd:`), or a prompt with apostrophes *and* a JSON
example like `{"outlook": 0}`:

```humon
{
    template: `You are an analyst. Judge today's move.
Reply with ONLY JSON: {"outlook": <-1..1>, "confidence": <0..1>}.`
}
```

Reading it back gives the exact multi-line string, apostrophe and double-quotes intact. (The
only character a backtick string can't hold is a literal backtick.)

## Metatags (annotations)

Humon metatags `@key:value` are exposed as a `dict[str, str]` on both nodes and the trove:

```python
root['title', 0].metatags     # {'focus': 'engineer'}
root['skills']['langs'].metatags  # {'group': 'languages'}
trove.metatags                # trove-level (file-scope) metatags
```

Use metatags to drive variants of the same data — read e.g. `@focus:` via `.metatags`
rather than hard-coding which entries to include. (configsys's own config/routes files don't
use metatags today.)

## Serialization (writing Humon back out)

Troves are **read-only** — there is no node-mutation API. To produce output you read
the trove and write your own format; `to_string` / `to_file` re-emit Humon itself:

```python
s = trove.to_string(h.WhitespaceFormat.MINIMAL, print_comments=False)
trove.to_file('out.hu', whitespace_format=h.WhitespaceFormat.PRETTY,
              indent_size=4, indent_with_tabs=False, print_comments=True)
```

`WhitespaceFormat` ∈ `{CLONED, MINIMAL, PRETTY}`. Colorized output is supported via
`use_colors=True` and an optional `color_table` keyed by `ColorCode` members.

## Stale README warnings

The humon-cy GitHub README predates the installed `0.1.0` API. In this version:

- annotations are `.metatags` — **not** `.annotations`
- next sibling is `.get_sibling()` — **not** `.sibling()`
- there is **no** `.token_string` property
- color codes are `PUNCMETATAG*` / `METATAGKEY` / `METATAGVALUE` — **not** `PUNCANNOTATE*` / `ANNOKEY`

When the README and `humon.pyx` disagree, trust `humon.pyx`.
