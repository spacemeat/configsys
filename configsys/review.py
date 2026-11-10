'''review.py — the Plugins review: which DIRECTION each change goes (docs/plugins.md §6a).

A review is never one two-way difference between this copy and its remote: that would show what
this machine has and the remote lacks as if the remote were taking it away (your own unpushed
commit read as "an update would undo it" — an update or sync never undoes your work, a push combines
it). Instead it is up to two kinds of SECTION:

- ↓ coming in (`IN`) — what the remote has that this copy doesn't, from where the two last agreed:
  what `update` would bring in (a plugin), what your other machines pushed (your primary), or, for a
  plugin not synced yet, what a sync would download (fetched into the inert review cache).
- ↑ going out (`OUT`) — what this copy has that the remote doesn't: commits made here, and edits not
  committed. Only when there are some: for your primary, what `plugin push` would share; for any
  other plugin, local work that a sync keeps (it stops rather than move past it or overwrite it).

A `Section` carries its direction, a title that names the action that would take it (as `{push}`,
`{sync}`, `{update}`, `{unlock}`, `{set_source}` — each surface names them its own way: the TUI with
the key from the keymap, the CLI with the command), its commits and its `File`s. `render` turns
sections into role-tagged lines that the TUI pane and `configsys plugin diff` both print, so the two
can't say different things. Every git call here is read-only (`--no-optional-locks`) and goes
through `primarygit.PrimaryRepo` (argv, scrubbed env); the fetches that come first are the caller's
(`plugins.fetch_ref` / `review_fetch`, `primarygit.fetch`).
'''

import os
from dataclasses import dataclass, field

from .primarygit import PrimaryRepo, _is_bytecode, count_phrase

IN, OUT = 'in', 'out'
ARROW = {IN: '↓', OUT: '↑'}
EMPTY_TREE = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'   # git's well-known empty tree

# The actions a title may name: placeholder -> (the keymap action in the `plugins` scope, its verb).
ACTIONS = {'push': ('push', 'push'), 'sync': ('sync', 'sync'), 'update': ('update', 'update'),
           'unlock': ('lock', 'unlock'), 'set_source': ('set-source', 'set-source')}

_MOST_READ = 256 * 1024                          # bytes of a working-tree file read for its diff


@dataclass
class File:
    '''One file's change. `lines` is the unified diff ([(kind, text)], kinds add/del/hunk/meta/ctx);
    `summary` the plain-language lines for a `.hu` file ([(kind, text)], kinds add/del/change) — None
    when there is none (not a `.hu` file, or one that doesn't read): show `lines` instead. An empty
    summary means the data didn't change (only comments or layout).'''
    path: str
    lines: list
    summary: list = None
    status: str = 'changed'                           # 'added' | 'deleted' | 'changed'


@dataclass
class Section:
    direction: str                                    # IN (↓) | OUT (↑)
    title: str                                        # may name actions: {push} {sync} {update} …
    files: list = field(default_factory=list)
    commits: list = field(default_factory=list)       # 'abc1234 subject', newest first
    note: str = ''                                    # one more line under the title

    def heading(self, act):
        '''The title line, its actions named by `act(placeholder)` (None: by their verbs). Only the
        placeholders are replaced — any other brace (git allows `{` in a ref name) is just text.'''
        name = act or (lambda p: ACTIONS[p][1])
        title = self.title
        for p in ACTIONS:
            if f'{{{p}}}' in title:
                title = title.replace(f'{{{p}}}', name(p))
        return f'{ARROW[self.direction]} {title}'


@dataclass
class Review:
    sections: list = field(default_factory=list)
    span: str = ''                                    # what is compared, in a few words
    error: str = ''                                   # nothing could be compared: why

    def files(self):
        '''Every (section, file), in order.'''
        return [(s, f) for s in self.sections for f in s.files]


# -- reading the two sides -------------------------------------------------------------------------

def _git(repo, *args):
    '''A read-only git call in `repo`: no optional locks (a diff must not refresh the index — under
    --pretend nothing may change), paths as they are (no octal quoting).'''
    return repo.git('--no-optional-locks', '-c', 'core.quotepath=off', *args)


def _text(data):
    try:
        return data.decode('utf-8')
    except (UnicodeDecodeError, AttributeError):
        return None


def _show(repo, rev, path):
    '''The text of `path` at `rev`, or None (absent there, or not UTF-8).'''
    if rev is None or rev == EMPTY_TREE:
        return None
    r = _git(repo, 'show', f'{rev}:{path}')
    return _text(r.out) if r.ok else None


def _summary(repo, path, a, b, status, new_text=None):
    '''The word summary of `path` going from rev `a` to rev `b` (b None: `new_text`, the working
    tree) — hudiff's, for a `.hu` file — or None when it has none (see File).'''
    if not path.endswith('.hu'):
        return None
    old = _show(repo, a, path) if status != 'added' else None
    new = (new_text if b is None else _show(repo, b, path)) if status != 'deleted' else None
    if (status != 'added' and old is None) or (status != 'deleted' and new is None):
        return None                                   # a side that couldn't be read (not UTF-8)
    from .hudiff import summarize
    return summarize(old, new)


def _diff(repo, a, b=None):
    '''[File] for the change from rev `a` to rev `b` (None: the working tree's tracked files).'''
    from .plugins import _parse_unified_diff
    r = _git(repo, 'diff', '--no-ext-diff', '--no-textconv', '--no-color', '--no-renames',
             '--src-prefix=a/', '--dst-prefix=b/', a, *([b] if b else []))
    if not r.ok:
        return []
    out = []
    for f in _parse_unified_diff(r.out.decode('utf-8', 'replace')):
        meta = [t for k, t in f['lines'] if k == 'meta']
        status = ('added' if any(t.startswith('new file') for t in meta) else
                  'deleted' if any(t.startswith('deleted file') for t in meta) else 'changed')
        new_text = None
        if b is None and status != 'deleted':
            new_text = _read(repo.root / f['path'])
        out.append(File(f['path'], f['lines'], _summary(repo, f['path'], a, b, status, new_text), status))
    return out


def _read(path):
    try:
        with open(path, 'rb') as fh:
            return _text(fh.read(_MOST_READ))
    except OSError:
        return None


def _untracked(repo):
    '''[File] for each untracked, not-ignored file (bytecode aside), shown as all added.'''
    r = _git(repo, 'ls-files', '--others', '--exclude-standard', '-z')
    out = []
    for raw in (r.out.split(b'\0') if r.ok else []):
        if not raw or _is_bytecode(raw):
            continue
        path = os.fsdecode(raw)
        text = _read(repo.root / path)
        lines = [('meta', 'new file, not committed')]
        lines += ([('add', '+' + ln) for ln in text.splitlines()] if text is not None
                  else [('meta', 'Binary file (or not UTF-8)')])
        out.append(File(path, lines, _summary(repo, path, None, None, 'added', text) if text is not None
                        else None, 'added'))
    return out


def _log(repo, span):
    r = _git(repo, 'log', '--format=%h %s', *span)
    return [ln for ln in r.out.decode('utf-8', 'replace').splitlines() if ln.strip()] if r.ok else []


def _rev(repo, rev):
    r = _git(repo, 'rev-parse', '--verify', '--quiet', f'{rev}^{{commit}}')
    return r.out.decode().strip() if r.ok and r.out.strip() else None


def _count(repo, span):
    r = _git(repo, 'rev-list', '--count', *span)
    try:
        return int(r.out.decode().strip()) if r.ok else 0
    except ValueError:
        return 0


@dataclass
class _Sides:
    incoming: list            # [File]: the remote's changes since the two last agreed
    behind: int               # commits on the remote, not here
    commits: list             # commits made here, not on the remote
    committed: list           # [File]: what those commits change
    edits: list               # [File]: uncommitted edits (tracked + untracked)


def _sides(repo, remote, local_span):
    '''The facts on both sides of a checkout. `remote` is the remote's commit (None: the remote has
    nothing to compare with); `local_span` the rev-list arguments naming the commits made HERE. The
    two sides part where they last agreed: HEAD when nothing was committed here (so the remote's side
    is exactly what moving to it changes), else the merge base — never the two tips against each
    other, which would show this machine's own commits reversed, as if coming in.'''
    commits = _log(repo, local_span)
    head = _rev(repo, 'HEAD')
    if not commits:
        base = head
    elif remote:
        mb = _git(repo, 'merge-base', 'HEAD', remote)
        base = mb.out.decode().strip() if mb.ok and mb.out.strip() else EMPTY_TREE
    else:
        base = EMPTY_TREE                             # no remote yet: every commit goes out
    incoming = _diff(repo, base, remote) if remote and base else []
    behind = _count(repo, [remote, '--not', 'HEAD']) if remote and head else 0
    committed = _diff(repo, base, 'HEAD') if commits and base else []
    edits = (_diff(repo, 'HEAD') if head else []) + _untracked(repo)
    return _Sides(incoming, behind, commits, committed, edits)


def _files(n):
    return count_phrase(n, 'file')


def _changes(n):
    return count_phrase(n, 'change')


# -- the reviews ---------------------------------------------------------------------------------

def primary(root, *, locked=False, stale=False):
    '''Your primary on its branch, against that branch on its remote as of the last fetch (`stale`:
    the fetch just tried failed — say so).'''
    repo = PrimaryRepo(root)
    branch = repo.branch()
    up = f'origin/{branch}'
    remote = _rev(repo, up)
    has_url = bool(repo.text('remote', 'get-url', '--push', 'origin'))
    s = _sides(repo, remote, [f'{up}..HEAD'] if remote else ['HEAD'])
    when = ' (as of the last fetch — it could not be fetched now)' if stale else ''
    sections = []
    if remote is None:
        title = (f'nothing to compare with yet — its remote has no {branch} branch' if has_url
                 else 'no remote yet — nothing comes in until it has one')
        sections.append(Section(IN, title))
    elif not s.incoming:
        sections.append(Section(IN, 'nothing new from your other machines' + when))
    else:
        n = _changes(s.behind)
        if locked:
            title = f'from your other machines: {n} — held back by your lock ({{unlock}} takes them in)'
        elif s.commits:
            title = (f'from your other machines: {n} — {{push}} combines them with yours (a sync '
                     f'can\'t: both sides changed)')
        else:
            title = f'{{sync}} would bring in from your other machines: {n}'
        mine = {f.path for f in s.edits} & {f.path for f in s.incoming}
        note = (f'your uncommitted edits touch {", ".join(sorted(mine))} too — a sync stops rather '
                f'than overwrite them' if mine else '')
        sections.append(Section(IN, title + when, s.incoming, note=note))
    if s.commits:
        n = _changes(len(s.commits))
        title = (f'{{push}} would share: {n}' + (' (its remote has none of it yet)' if remote is None else '')
                 if has_url else f'only on this machine: {n} — it has no remote yet ({{set_source}}, '
                                 f'then {{push}})')
        sections.append(Section(OUT, title, s.committed, s.commits))
    if s.edits:
        sections.append(Section(OUT, f'edits not committed yet: {_files(len(s.edits))} — {{push}} asks '
                                     f'whether to include them', s.edits))
    return Review(sections, f'this copy ⇄ {branch} on its remote')


def synced(root, remote, *, frm, to, locked=False):
    '''A synced plugin (not your primary on a branch) against the remote's `to` (fetched: commit
    `remote`), moving from `frm` (its declared ref, or HEAD).'''
    repo = PrimaryRepo(root)
    s = _sides(repo, remote, ['HEAD', '--not', '--remotes', '--tags'])
    if not s.incoming:
        sections = [Section(IN, 'up to date — nothing to pull in')]
    elif locked:
        sections = [Section(IN, f'held back by your lock: {frm} → {to} ({{unlock}}, then {{update}} '
                                f'takes it)', s.incoming)]
    else:
        sections = [Section(IN, f'{{update}} would bring in: {frm} → {to}', s.incoming)]
    if s.commits:
        sections.append(Section(OUT, f'committed here, not on its remote: '
                                     f'{count_phrase(len(s.commits), "commit")} — a sync or update '
                                     f'leaves them in place (it stops rather than move past them)',
                                s.committed, s.commits))
    if s.edits:
        sections.append(Section(OUT, f'edited here, not committed: {_files(len(s.edits))} — a sync or '
                                     f'update keeps your edits (it stops rather than overwrite one)',
                                s.edits))
    return Review(sections, f'{frm} → {to}')


def unsynced(cache, base, target, *, base_ref, to):
    '''A plugin not synced yet, read from its inert review-cache repo `cache`: commit `base` (the
    declared ref; the empty tree for "everything") -> commit `target` (the remote's `to`).'''
    repo = PrimaryRepo(cache)
    files = _diff(repo, base or EMPTY_TREE, target)
    if base_ref is None:
        title = f'not synced — {{sync}} would download all of {to}: {_files(len(files))}'
        span = f'everything at {to}'
    elif files:
        title = f'not synced — {{update}} would download {to}; what it changes from your declared {base_ref}:'
        span = f'{base_ref} → {to}'
    else:
        title = f'not synced — {base_ref} and {to} are identical'
        span = f'{base_ref} → {to}'
    return Review([Section(IN, title, files)], span)


def outgoing(root, upstream):
    '''The ↑ section a push of the checkout at `root` would send: HEAD's commits that `upstream`
    lacks (every commit when there is no upstream yet), and what they change.'''
    repo = PrimaryRepo(root)
    remote = _rev(repo, upstream) if upstream else None
    commits = _log(repo, [f'{upstream}..HEAD'] if remote else ['HEAD'])
    if not commits:
        return Section(OUT, 'nothing to share')
    if remote:
        mb = _git(repo, 'merge-base', 'HEAD', remote)
        base = mb.out.decode().strip() if mb.ok and mb.out.strip() else EMPTY_TREE
    else:
        base = EMPTY_TREE
    return Section(OUT, f'{{push}} would share: {_changes(len(commits))}', _diff(repo, base, 'HEAD'),
                   commits)


# -- rendering (the TUI pane and `configsys plugin diff` both print these) -------------------------

_STATUS = {'added': '  (new file)', 'deleted': '  (deleted)'}
_GIT_HEADERS = ('index ', '--- ', '+++ ', 'new file mode', 'deleted file mode')   # the file line says it


def render(sections, act=None, *, raw=False, heading=True, commits=True, most_commits=20):
    '''Role-tagged lines [(kind, text)] for `sections`: each title (kind 'head-in' / 'head-out',
    its actions named by `act`, see Section.heading — left out with `heading` False), its note, its
    commits (unless `commits` False), then each file with its word summary — or, `raw` (or a file with
    no summary), its unified diff. Kinds: head-in, head-out, note, commit, file, add, del, change
    (summaries), hunk, meta, ctx (diff lines). The push preview and its question print the ↑ section
    this way too (primarygit).'''
    out = []
    for s in sections:
        if heading:
            out.append((f'head-{s.direction}', s.heading(act)))
        if s.note:
            out.append(('note', f'    {s.note}'))
        for c in (s.commits[:most_commits] if commits else ()):
            out.append(('commit', f'    {c}'))
        if commits and len(s.commits) > most_commits:
            out.append(('commit', f'    … and {len(s.commits) - most_commits} more'))
        for f in s.files:
            if raw:
                out.append(('meta', f'diff --git a/{f.path} b/{f.path}'))
                out += list(f.lines)
                continue
            out.append(('file', f'  {f.path}{_STATUS.get(f.status, "")}'))
            if f.summary is None:                     # no words for it: its diff, minus git's headers
                out += [(k, f'    {t}') for k, t in f.lines
                        if not (k == 'meta' and t.startswith(_GIT_HEADERS))]
            elif not f.summary:
                out.append(('note', '    only comments or layout changed'))
            else:
                out += [(k, f'    {t}') for k, t in f.summary]
    return out
