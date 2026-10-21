'''primarygit.py — commit configsys's own edits to your primary plugin, locally (docs/todo/
primary-push-plan.md, phase 1).

Every CLI command and every TUI action that may write is bracketed: `snapshot()` records which paths
in the primary's checkout are already dirty, and `commit()` afterwards commits exactly the paths that
became dirty in between — with a message saying what was done. So configsys's edits land as small,
undoable commits on the primary's branch (ready for `plugin push`), while edits you were making by
hand are never swept in: a file that already had uncommitted changes of yours is left for you to
commit, and you're told.

Nothing happens under --pretend, when there's no primary, when it isn't a git checkout, or when it
isn't on a branch (a tag-pinned primary is frozen; its edits stay uncommitted, noted once). With no
git identity configured, the commit uses a repo-local fallback (`<user>@<host>`), noted once.
'''

import getpass
import hashlib
import shlex
import socket
from pathlib import Path


class Snapshot:
    def __init__(self, root, name, dirty):
        self.root, self.name, self.dirty = root, name, dirty
        self.hashes = {p: _hash(root / p) for p in dirty}     # to spot configsys writing into them


def _hash(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    except OSError:
        return None


def primary_root(ctx):
    '''(dir, name) of the synced primary plugin when configsys may commit to it, else None.'''
    if getattr(getattr(ctx, 'runner', None), 'pretend', False):
        return None
    from . import plugins
    try:
        decls = plugins.declared(ctx.paths.user_config_file)
    except Exception:                                  # noqa: BLE001 — no/odd config: nothing to do
        return None
    name = plugins.primary_name(decls)
    if not name:
        return None
    root = Path(ctx.paths.plugins_dir) / name
    return (root, name) if (root / '.git').exists() else None


def _git(ctx, root, args):
    return ctx.runner.run(f'git -C {shlex.quote(str(root))} {args}', capture=True)


def _dirty(ctx, root):
    '''The set of repo-relative paths with uncommitted changes (tracked or untracked), or None.'''
    r = _git(ctx, root, 'status --porcelain -z --untracked-files=all')
    if r is None or not r.ok:
        return None
    out, parts = set(), (r.stdout or '').split('\0')
    i = 0
    while i < len(parts):
        entry = parts[i]
        if len(entry) > 3:
            out.add(entry[3:])
            if entry[0] in 'RC':                       # a rename/copy carries its source next
                i += 1
        i += 1
    return out


def snapshot(ctx):
    '''What's already dirty in the primary before an edit, or None when configsys won't commit.'''
    pr = primary_root(ctx)
    if pr is None:
        return None
    dirty = _dirty(ctx, pr[0])
    return Snapshot(pr[0], pr[1], dirty) if dirty is not None else None


def _note_once(ctx, key, text, notes):
    seen = ctx.__dict__.setdefault('_primarygit_noted', set())
    if key not in seen:
        seen.add(key)
        notes.append(text)


def commit(ctx, snap, message):
    '''Commit the paths that became dirty since `snap`, as `message`. Returns a list of notes to show
    (empty when there was nothing to commit or it went through quietly).'''
    if snap is None:
        return []
    now = _dirty(ctx, snap.root)
    if now is None:
        return []
    changed = sorted(now - snap.dirty)
    notes = []
    mixed = sorted(p for p in snap.dirty if _hash(snap.root / p) != snap.hashes.get(p))
    if mixed:                                          # configsys wrote into a file you were editing
        notes.append(f'{snap.name}: {", ".join(mixed)} also has edits of your own, so configsys '
                     f'left it uncommitted — commit it yourself (in {snap.root}).')
    if not changed:
        return notes
    branch = _git(ctx, snap.root, 'symbolic-ref --short -q HEAD')
    if branch is None or not branch.ok or not (branch.stdout or '').strip():
        _note_once(ctx, 'detached', f'{snap.name} is pinned to a tag or commit, so configsys saved '
                   f'your changes there but did not commit them (a primary normally follows its '
                   f'branch; see `configsys plugin list`).', notes)
        return notes
    ident = ''
    who = _git(ctx, snap.root, 'config user.email')
    if who is None or not who.ok or not (who.stdout or '').strip():
        user, host = getpass.getuser(), socket.gethostname() or 'localhost'
        ident = f'-c user.name={shlex.quote(user)} -c user.email={shlex.quote(f"{user}@{host}")} '
        _note_once(ctx, 'ident', f'no git identity is set, so commits to {snap.name} are signed '
                   f'{user}@{host} — set yours with `git config --global user.name/user.email`.',
                   notes)
    paths = ' '.join(shlex.quote(p) for p in changed)
    body = f'Made by configsys on {socket.gethostname() or "this machine"}.'
    add = _git(ctx, snap.root, f'add -A -- {paths}')
    if add is None or not add.ok:
        return notes + [f'could not commit to {snap.name} ({(add.stderr or "").strip() if add else "git"})']
    c = _git(ctx, snap.root, f'{ident}commit -q -m {shlex.quote(message)} -m {shlex.quote(body)} '
                             f'-- {paths}')
    if c is None or not c.ok:
        return notes + [f'could not commit to {snap.name}: '
                        f'{((c.stderr or c.stdout or "") if c else "").strip()[:200]}']
    return notes
