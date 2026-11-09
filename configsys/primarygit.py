'''primarygit.py — commit configsys's own edits to your primary plugin, locally (docs/done/
primary-push-plan.md, phase 1), and publish them (`push`, phases 3–4).

Every CLI command and every TUI action is bracketed by a WRITE JOURNAL (docs/done/
primary-journal-plan.md): `snapshot()` opens it (no git — it costs nothing), each configsys writer
calls `will_write(path)` just before it writes a file or a tree inside the primary, and `commit()`
afterwards commits exactly the recorded paths that changed — with a message saying what was done. So
configsys's edits land as small, undoable commits on the primary's branch (ready for `plugin push`),
while edits you make by hand are never swept in: a recorded file that already had uncommitted
changes of yours is left for you to commit, and a change nobody recorded (yours, made while the
command ran) is left too, and named. An action that writes nothing spends no git call.

Nothing happens under --pretend, when there's no primary, when it isn't a git checkout, or when it
isn't on a branch (a tag-pinned primary is frozen; its edits stay uncommitted, noted once). With no
git identity (git can't form one: no `user.name` / `user.email`, nor `GIT_AUTHOR_*` / `EMAIL`),
nothing is committed and you're told once how to set one — configsys never invents `<login>@<host>`.
Commit bodies name the configsys machine (`machine:`), never the hostname. The bracket is
best-effort: whatever goes wrong in it is a note, never a crash of the command.

Every git call goes through `PrimaryRepo` (docs/done/primary-safety-plan.md): argv lists, never a
shell; bytes in and `os.fsdecode` out, so a file name that isn't UTF-8 is just a name; literal
pathspecs, passed on stdin, so a `[` in a name is no glob and a long list no overflow; and an env
without git's repository-locating variables, so a `GIT_DIR` from a vcsh / yadm session can't send a
commit to another repository.
'''

import hashlib
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from . import layers


# git's repository-locating variables (`git rev-parse --local-env-vars`, as of git 2.34) — removed from
# the env of every primary git call, so the primary is always the repository at `PrimaryRepo.root`
_LOCATING_VARS = frozenset({
    'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_CONFIG', 'GIT_CONFIG_PARAMETERS', 'GIT_CONFIG_COUNT',
    'GIT_OBJECT_DIRECTORY', 'GIT_DIR', 'GIT_WORK_TREE', 'GIT_IMPLICIT_WORK_TREE', 'GIT_GRAFT_FILE',
    'GIT_INDEX_FILE', 'GIT_NO_REPLACE_OBJECTS', 'GIT_REPLACE_REF_BASE', 'GIT_PREFIX',
    'GIT_INTERNAL_SUPER_PREFIX', 'GIT_SHALLOW_FILE', 'GIT_COMMON_DIR'})
_locating_cache = []


def _locating_vars():
    '''The variables to scrub: git's own list when it can say, unioned with the known ones.'''
    if not _locating_cache:
        try:
            out = subprocess.run(['git', 'rev-parse', '--local-env-vars'], capture_output=True,
                                 text=True, env=_scrub(os.environ, _LOCATING_VARS), timeout=10).stdout
            _locating_cache.append(_LOCATING_VARS | set(out.split()))
        except Exception:                              # noqa: BLE001 — the known list will do
            _locating_cache.append(_LOCATING_VARS)
    return _locating_cache[0]


def _scrub(env, names):
    return {k: v for k, v in env.items() if k not in names}


class GitResult:
    '''One git run: `out` is the raw bytes; `stdout` decodes them losslessly (surrogateescape, so
    a non-UTF-8 name round-trips through `os.fsencode`).'''

    def __init__(self, returncode, out, err):
        self.returncode, self.out = returncode, out or b''
        self.stdout = self.out.decode('utf-8', 'surrogateescape')
        self.stderr = (err or b'').decode('utf-8', 'replace')

    @property
    def ok(self):
        return self.returncode == 0


def _is_bytecode(path):
    '''A git status path (bytes) that is Python bytecode: under a `__pycache__/` dir, or *.pyc.'''
    return path.endswith(b'.pyc') or b'__pycache__' in path.rstrip(b'/').split(b'/')


class PrimaryRepo:
    '''The one way this module runs git on the primary's checkout at `root`.'''

    def __init__(self, root):
        self.root = Path(root)

    def env(self):
        return _scrub(os.environ, _locating_vars())

    def network_env(self, interactive):
        '''The env for fetch / push. Interactive (the CLI on a terminal): git may ask for a passphrase.
        Otherwise it never prompts: no terminal prompt, no credential-manager popup, and ssh in
        BatchMode — appended to YOUR ssh command (git's order: $GIT_SSH_COMMAND, else core.sshCommand,
        else the $GIT_SSH program, else ssh), so a key or proxy you configured there keeps working.'''
        env = self.env()
        if interactive:
            return env
        env.update(GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never')
        ssh = (os.environ.get('GIT_SSH_COMMAND') or self.config('core.sshCommand')
               or (shlex.quote(os.environ['GIT_SSH']) if os.environ.get('GIT_SSH') else 'ssh'))
        env['GIT_SSH_COMMAND'] = ssh if 'BatchMode' in ssh else f'{ssh} -o BatchMode=yes'
        return env

    def git(self, *args, paths=None, env=None, input=None):
        '''Run `git <args>` in the primary. `paths` go as a NUL-separated pathspec list on stdin
        (`--pathspec-from-file`), never on the command line. An EMPTY `paths` runs nothing: to git an
        empty pathspec file is no pathspec — every path (primary-17).'''
        if paths is not None and not paths:
            return GitResult(0, b'', b'')
        argv = ['git', '-C', str(self.root), '--literal-pathspecs', *args]
        if paths is not None:
            argv += ['--pathspec-from-file=-', '--pathspec-file-nul']
            input = b'\0'.join(os.fsencode(p) for p in paths)
        cp = subprocess.run(argv, input=input, capture_output=True, env=env or self.env(),
                            stdin=subprocess.DEVNULL if input is None else None)
        return GitResult(cp.returncode, cp.stdout, cp.stderr)

    def text(self, *args):
        '''The trimmed output of a successful `git <args>`, else ''.'''
        r = self.git(*args)
        return r.stdout.strip() if r.ok else ''

    def config(self, key):
        return self.text('config', key)

    def branch(self):
        return self.text('symbolic-ref', '--short', '-q', 'HEAD')

    def has_ref(self, ref):
        return self.git('rev-parse', '--verify', '--quiet', ref).ok

    def ahead_behind(self, upstream):
        '''(commits on HEAD not on `upstream`, commits on `upstream` not on HEAD); (0, 0) if unknown.'''
        try:
            a, b = self.text('rev-list', '--left-right', '--count', f'HEAD...{upstream}').split()
            return int(a), int(b)
        except ValueError:
            return 0, 0

    def dirty(self):
        '''The set of paths with uncommitted changes (tracked or untracked), or None. git-ignored
        files never show, and neither does untracked Python bytecode (`__pycache__/`, `*.pyc`) —
        importing a code plugin can leave some, and it is nobody's work.'''
        r = self.git('--no-optional-locks', 'status', '--porcelain', '-z', '--untracked-files=all')
        if not r.ok:
            return None
        out, parts = set(), r.out.split(b'\0')
        i = 0
        while i < len(parts):
            entry = parts[i]
            if entry[:3] == b'?? ' and _is_bytecode(entry[3:]):
                pass
            elif len(entry) > 3:
                out.add(os.fsdecode(entry[3:]))
                xy = entry[:2]                         # a rename/copy carries its source next — in
                if b'R' in xy or b'C' in xy:           # either column (` R` after `git add -N`)
                    i += 1
                    if xy[1:] == b'R' and i < len(parts) and parts[i]:
                        out.add(os.fsdecode(parts[i]))   # a worktree rename's source is still in
                        #                                  the index: its deletion is a change too
            i += 1
        return out

    def unmerged(self):
        r = self.git('diff', '--name-only', '--diff-filter=U', '-z')
        return sorted(os.fsdecode(p) for p in r.out.split(b'\0') if p) if r.ok else []

    def unmerged_entries(self, paths):
        '''{path: {stage: (mode, blob)}} for the unmerged index entries of `paths` (a few: ls-files
        takes no pathspec on stdin, so they go after `--` — literal, like every pathspec here).'''
        r = self.git('ls-files', '-u', '-z', '--', *paths)
        out = {}
        for rec in (r.out.split(b'\0') if r.ok else []):
            if b'\t' in rec:
                meta, name = rec.split(b'\t', 1)
                mode, blob, stage = meta.decode().split()
                out.setdefault(os.fsdecode(name), {})[int(stage)] = (mode, blob)
        return out

    def stage(self, n, path):
        '''The bytes of `path` at merge stage `n` (1 base, 2 ours, 3 theirs), or None.'''
        r = self.git('show', f':{n}:{path}')
        return r.out if r.ok else None

    def in_progress(self):
        ''''merge' / 'rebase' / 'cherry-pick' / 'revert' when the checkout is in the middle of one
        (yours, or one an interrupted configsys left), else None.'''
        markers = (('MERGE_HEAD', 'merge'), ('rebase-merge', 'rebase'), ('rebase-apply', 'rebase'),
                   ('CHERRY_PICK_HEAD', 'cherry-pick'), ('REVERT_HEAD', 'revert'))
        r = self.git('rev-parse', *(a for m, _ in markers for a in ('--git-path', m)))   # one spawn
        paths = r.stdout.splitlines() if r.ok else []
        for p, (_marker, what) in zip(paths, markers):
            if p and (Path(p) if os.path.isabs(p) else self.root / p).exists():
                return what
        return None

    def ignored(self):
        '''The set of ignored, untracked paths in the checkout (a `.cfs` dir's secrets), or set().'''
        r = self.git('ls-files', '--others', '--ignored', '--exclude-standard', '-z')
        return {os.fsdecode(p) for p in r.out.split(b'\0') if p} if r.ok else set()

    def incoming(self, upstream):
        '''The paths `upstream` changed since it and HEAD diverged.'''
        r = self.git('diff', '--name-only', '-z', f'HEAD...{upstream}')
        return {os.fsdecode(p) for p in r.out.split(b'\0') if p} if r.ok else set()


class Snapshot:
    '''One open bracket — the write journal of a CLI command or a TUI action. `recorded` holds the
    repo-relative paths configsys said it would write ('' = the whole checkout); `before` is what was
    already dirty when the first of them was announced (None until then — nothing written yet), and
    `hashes` the bytes' hash of each already-dirty file under a recorded path, taken before configsys
    wrote, so commit() can tell "configsys wrote into a file you were editing".'''

    def __init__(self, root, name):
        self.root, self.name = Path(root), name
        self.real = os.path.realpath(self.root)
        self.recorded = set()
        self.before = None
        self.hashes = {}
        self.unknown = False                                  # git status failed: commit nothing
        self.committed = False                                # set when commit() made a commit


def _hash(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    except OSError:
        return None


def _under(rel, prefix):
    '''Is repo-relative `rel` the recorded path `prefix` or inside it?'''
    return prefix == '' or rel == prefix or rel.startswith(prefix + '/')


_open_journal = []                                     # the open bracket (at most one), else empty
_root_cache = {}


def primary_root(ctx):
    '''(dir, name) of the synced primary plugin when configsys may commit to it, else None. Cached
    per user-config file and mtime (the TUI asks on every keypress).'''
    if getattr(getattr(ctx, 'runner', None), 'pretend', False):
        return None
    from . import plugins
    try:
        cfg = Path(ctx.paths.user_config_file)
        key = (str(cfg), cfg.stat().st_mtime_ns, str(ctx.paths.plugins_dir))
    except Exception:                                  # noqa: BLE001 — no/odd config: nothing to do
        return None
    if key not in _root_cache:
        try:
            name = plugins.primary_name(plugins.declared(cfg))
        except Exception:                              # noqa: BLE001
            name = None
        _root_cache.clear()
        _root_cache[key] = name
    name = _root_cache[key]
    if not name:
        return None
    root = Path(ctx.paths.plugins_dir) / name
    return (root, name) if (root / '.git').exists() else None


def snapshot(ctx):
    '''Open the write journal for one command / action: the bracket commit() closes. None when
    configsys won't commit (no primary, --pretend, …) — then `will_write` records nothing. Runs no
    git; never stops a command.'''
    _open_journal.clear()
    try:
        pr = primary_root(ctx)
        if pr is None:
            return None
        snap = Snapshot(*pr)
        _open_journal.append(snap)
        return snap
    except Exception:                                  # noqa: BLE001 — best-effort, never a crash
        return None


def _relative(snap, path):
    '''`path` relative to the primary's checkout ('' for the checkout itself), or None when it is
    outside. The parent is resolved, not the path itself: a symlink inside the primary is a path
    inside it, wherever it points.'''
    a = os.path.abspath(os.fspath(path))
    real = os.path.join(os.path.realpath(os.path.dirname(a)), os.path.basename(a))
    if real == snap.real:
        return ''
    if not real.startswith(snap.real + os.sep):
        return None
    return Path(os.path.relpath(real, snap.real)).as_posix()


def will_write(path):
    '''Say that configsys is about to write — create, change or delete — `path`, a file or a whole
    tree. Inside an open bracket whose primary holds it, the path is recorded and commit() commits
    what changes there. Call it BEFORE writing: the first call of a bracket reads what was already
    dirty (one `git status`), so your own edits stay yours. Outside the primary, or with no bracket
    open, it does nothing. Never raises.'''
    if not _open_journal:
        return
    snap = _open_journal[0]
    try:
        rel = _relative(snap, path)
        if rel is None or snap.unknown:
            return
        if snap.before is None:
            dirty = PrimaryRepo(snap.root).dirty()
            if dirty is None:
                snap.unknown = True
                return
            snap.before = dirty
        if any(_under(rel, r) for r in snap.recorded):
            return                                     # already recorded (or inside a recorded tree)
        snap.recorded.add(rel)
        for p in snap.before:
            if _under(p, rel) and p not in snap.hashes:
                snap.hashes[p] = _hash(snap.root / p)
    except Exception:                                  # noqa: BLE001 — best-effort, never a crash
        snap.unknown = True


def _note_once(ctx, key, text, notes):
    seen = ctx.__dict__.setdefault('_primarygit_noted', set())
    if key not in seen:
        seen.add(key)
        notes.append(text)


def commit(ctx, snap, message):
    '''Close the bracket: commit the recorded paths that changed since `snap` opened, as `message`.
    Returns a list of notes to show (empty when nothing was written or it went through quietly).
    Never raises.'''
    if _open_journal and _open_journal[0] is snap:
        _open_journal.clear()
    if snap is None or not snap.recorded or snap.unknown:
        return []
    try:
        return _commit(ctx, snap, message)
    except Exception as e:                             # noqa: BLE001 — best-effort, never a crash
        return [f'could not commit to {snap.name}: {e}']


def _names(paths, most=3):
    shown = ', '.join(paths[:most])
    return shown + (f' and {len(paths) - most} more' if len(paths) > most else '')


def _commit(ctx, snap, message):
    repo = PrimaryRepo(snap.root)
    busy = repo.in_progress()
    if busy:                                           # never stage into a half-done merge / rebase
        return [f'could not commit to {snap.name}: it is in the middle of a {busy} — finish it, or '
                f'`git -C {snap.root} {busy} --abort`, and configsys commits again from then on.']
    now = repo.dirty()
    if now is None:
        return []
    ours = {p for p in now if any(_under(p, r) for r in snap.recorded)}
    changed = sorted(ours - snap.before)
    notes = []
    mixed = sorted(p for p in ours & snap.before if _hash(snap.root / p) != snap.hashes.get(p))
    if mixed:                                          # configsys wrote into a file you were editing
        notes.append(f'{snap.name}: {_names(mixed)} also has edits of your own, so configsys '
                     f'left it uncommitted — commit it yourself (in {snap.root}).')
    stray = sorted(now - snap.before - ours)
    if stray:                                          # changed meanwhile, but not by configsys
        notes.append(f'{snap.name}: {_names(stray)} changed while configsys was working, not by '
                     f'configsys, so it was left uncommitted — yours to commit (in {snap.root}).')
    if not changed:
        return notes
    if not repo.branch():
        _note_once(ctx, 'detached', f'{snap.name} is pinned to a tag or commit, so configsys saved '
                   f'your changes there but did not commit them (a primary normally follows its '
                   f'branch; see `configsys plugin list`).', notes)
        return notes
    if not _has_ident(ctx, repo):
        _note_once(ctx, 'ident', _no_ident(snap.name, snap.root), notes)
        return notes
    ok, why = _commit_paths(repo, [], changed, message, _made_by(ctx), hooks=False)
    if not ok:
        return notes + [f'could not commit to {snap.name}: {why}']
    snap.committed = True
    return notes


def _commit_paths(repo, ident, paths, subject, body, hooks=True):
    '''Stage and commit exactly `paths` (literal, through stdin). (ok, git's complaint). configsys's
    own edits commit with `hooks=False` (`--no-verify`: a global pre-commit hook must not run on every
    TUI write); your signing setting applies either way.'''
    add = repo.git('add', '-A', paths=paths)
    if not add.ok:
        return False, _err(add, 200)
    committed = repo.git(*ident, 'commit', '-q', *([] if hooks else ['--no-verify']), '-m', subject,
                         '-m', body, paths=paths)
    return committed.ok, _err(committed, 200)


def _machine(ctx):
    '''This box's configsys machine name (the `machine:` setting — not a `--machine` working target,
    not the hostname), or None for the default one-machine setup.'''
    try:
        return ctx.config.configured_machine()
    except Exception:                                  # noqa: BLE001
        return None


def _made_by(ctx, what='Made by configsys'):
    m = _machine(ctx)
    return f'{what} on {m}.' if m else f'{what}.'


def _has_ident(ctx, repo):
    '''Can git form an author and committer for the primary (config, or GIT_AUTHOR_* / EMAIL in the
    environment)? Asked once per command.'''
    seen = ctx.__dict__.setdefault('_primarygit_ident', {})
    key = str(repo.root)
    if key not in seen:
        seen[key] = repo.git('var', 'GIT_AUTHOR_IDENT').ok and repo.git('var', 'GIT_COMMITTER_IDENT').ok
    return seen[key]


def _no_ident(name, root):
    return (f'no git identity is set, so configsys left your changes to {name} uncommitted — set one '
            f'(`git config --global user.name "Your Name"` and `user.email you@example.com`); commit '
            f'these yourself in {root}, or they\'re offered as hand edits at your next push.')


# -- where the primary stands (phase 2: the Plugins row, the header chip, `plugin list`) ----------

@dataclass(frozen=True)
class PrimaryState:
    '''Where the primary stands against its remote branch, as of the last fetch: `ahead` commits not
    pushed, `behind` commits from your other machines, `dirty` uncommitted edits, `first_push` — the
    remote has never had this branch (so every commit counts as not pushed yet).'''
    name: str
    branch: str
    ahead: int = 0
    behind: int = 0
    dirty: bool = False
    first_push: bool = False


def local_work(root, source=None):
    """What deleting the checkout at `root` would lose for good — `[]` when nothing: one line each
    for uncommitted changes, commits no remote has, stashes, a repo with no remote at all, and a
    plugin authored in place (its `source:` IS this dir — `plugin init`). The guard every rmtree of a
    plugin clone asks first (review-2026-11-2 A3). Best-effort: a git error reads as "can't tell",
    which is reported as work (refuse rather than guess)."""
    from . import plugins as _plugins
    root = Path(root)
    if not root.exists():
        return []
    lost = []
    if source is not None and _plugins.is_local_authored(source, root):
        lost.append('it is its own source (authored here, e.g. by `plugin init`) — the only copy')
    if not (root / '.git').exists():
        return lost
    try:
        repo = PrimaryRepo(root)
        dirty = repo.dirty()
        if dirty is None:
            return lost + ['git could not read its status']
        if dirty:
            lost.append(f'{len(dirty)} uncommitted change(s): {", ".join(sorted(dirty)[:5])}'
                        + (' …' if len(dirty) > 5 else ''))
        remotes = repo.text('remote')
        if not remotes:
            n = repo.text('rev-list', '--count', '--all')
            if n and n != '0' and not lost:
                lost.append(f'no remote: its {n} commit(s) exist only here')
        else:
            n = repo.text('rev-list', '--count', 'HEAD', '--branches', '--not', '--remotes', '--tags')
            if n and n != '0':
                lost.append(f'{n} commit(s) not on any remote (not pushed yet)')
        stashes = [s for s in repo.text('stash', 'list').splitlines() if s]
        if stashes:
            lost.append(f'{len(stashes)} stash(es)')
    except Exception:                                  # noqa: BLE001
        lost.append('git could not inspect it')
    return lost


def state(ctx):
    '''The primary's `PrimaryState`, or None (no primary, not a git checkout, not on a branch, no
    remote, --pretend). Local and cheap — `fetch` first to count what the remote has.'''
    try:
        pr = primary_root(ctx)
        if pr is None:
            return None
        repo = PrimaryRepo(pr[0])
        branch = repo.branch()
        if not branch:
            return None
        first = not repo.has_ref(f'origin/{branch}')
        if not first:
            ahead, behind = repo.ahead_behind(f'origin/{branch}')
        elif repo.text('remote', 'get-url', '--push', 'origin'):
            ahead, behind = int(repo.text('rev-list', '--count', 'HEAD') or 0), 0   # never pushed
        else:
            return None
        return PrimaryState(pr[1], branch, ahead, behind, bool(repo.dirty()), first)
    except Exception:                                  # noqa: BLE001 — best-effort, never a crash
        return None


def head(ctx):
    '''The primary's HEAD commit, or None — so a caller can tell whether a push / undo moved it.'''
    try:
        pr = primary_root(ctx)
        return (PrimaryRepo(pr[0]).text('rev-parse', 'HEAD') or None) if pr else None
    except Exception:                                  # noqa: BLE001
        return None


def fetch(ctx):
    '''Fetch the primary's remote (non-interactive, refs only — the working tree is untouched), so
    `state()` can count what your other machines pushed. Through the push URL, as `push` does (a
    private repo you can push to is one you can fetch). Best-effort; False if it couldn't.'''
    try:
        pr = primary_root(ctx)
        if pr is None:
            return False
        repo = PrimaryRepo(pr[0])
        url = repo.text('remote', 'get-url', '--push', 'origin')
        return bool(url) and _fetch(repo, url, interactive=False).ok
    except Exception:                                  # noqa: BLE001
        return False


def _fetch(repo, url, interactive):
    return repo.git('fetch', '--quiet', '--prune', url, '+refs/heads/*:refs/remotes/origin/*',
                    env=repo.network_env(interactive))


def glyphs(st):
    '''The compact marks for the Plugins row: ↑N to push, ↓N to sync, ● uncommitted edits.'''
    if not st:
        return ''
    out = []
    if st.ahead:
        out.append(f'↑{st.ahead}')
    if st.behind:
        out.append(f'↓{st.behind}')
    if st.dirty:
        out.append('●')
    return ' '.join(out)


def chip(st, *, hide_ahead=False):
    '''The header chip text, or '' when there's nothing to push or sync. `hide_ahead` (under
    `primary-push: auto` / `auto-on-quit`, where configsys pushes for you) leaves out the ↑ part.'''
    ahead = 0 if hide_ahead or not st else st.ahead
    if not st or not (ahead or st.behind):
        return ''
    parts = []
    if ahead:
        parts.append(f'↑{st.ahead} to push')
    if st.behind:
        parts.append(f'↓{st.behind} to sync')
    return f'{st.name}: ' + ', '.join(parts)


def describe(st):
    '''Where the primary stands, in words (for `plugin list`), or '' when it's level and clean.'''
    if not st:
        return ''
    parts = []
    if st.ahead:
        parts.append(f'{st.ahead} change{"s" if st.ahead != 1 else ""} not pushed yet '
                     f'(`plugin push` shares {_them(st.ahead)})')
    if st.behind:
        parts.append(f'{st.behind} change{"s" if st.behind != 1 else ""} from your other '
                     f'machines (as of the last fetch) — `plugin sync` brings them in')
    if st.dirty:
        parts.append('edits not committed yet')
    if st.ahead and st.behind:
        parts.append('both sides changed — `plugin push` combines them')
    return '; '.join(parts)


# -- publishing it (phase 3: `configsys plugin push`, the Plugins `P` key, the `primary-push` setting) --

PUSH_MODES = layers.SETTING_CHOICES['primary-push']

# What each `primary-push` mode does: after a CLI command that committed ('push', 'hint' = say it
# isn't pushed yet, None = quiet), when you quit the TUI ('push', 'ask', None) and on quit-force
# ('push', 'note' = leave a line, None), and whether the header chip leaves out ↑ (configsys pushes
# those for you).
PUSH_POLICY = {
    'ask':          {'after_cli': 'hint', 'quit': 'ask',  'quit_force': 'note', 'hide_ahead': False},
    'auto':         {'after_cli': 'push', 'quit': 'push', 'quit_force': 'note', 'hide_ahead': True},
    'auto-on-quit': {'after_cli': 'hint', 'quit': 'push', 'quit_force': 'push', 'hide_ahead': True},
    'manual':       {'after_cli': None,   'quit': None,   'quit_force': None,   'hide_ahead': False},
}


def _verify(ctx):
    '''`primary-verify: signed` on this machine?'''
    try:
        return ctx.config.primary_verify() == 'signed'
    except Exception:                                  # noqa: BLE001 — a fake/odd ctx: off
        return False


def push_mode(ctx):
    '''The `primary-push` setting: 'ask' (default), 'auto', 'auto-on-quit' or 'manual'.'''
    try:
        return ctx.config.primary_push()
    except Exception:                                  # noqa: BLE001 — a fake/odd ctx: the default
        return 'ask'


class Choice(NamedTuple):
    answer: object                                     # what `ask` returns for it
    key: str                                           # its one-letter shortcut
    label: str


_KEEP = (Choice('mine', 'm', "Keep this machine's"), Choice('theirs', 't', "Keep the other machine's"))
_STOP = Choice('stop', 's', 'Stop — push nothing')

# Every question `push` asks: kind -> (choices, the answer for Enter / Esc, the answer when nobody can
# be asked). Both are the cautious one, except that an unattended push needs no "send it?" — the
# command was the consent. The CLI and the TUI render these same choices.
QUESTIONS = {
    'include-own': ((Choice(False, 'n', 'Leave them out (they stay here)'), Choice(True, 'y', 'Include them')),
                    False, False),
    'overlap': ((Choice('stop', 's', 'Stop — push nothing, change nothing'),
                 Choice('include', 'i', 'Include them in this push')), 'stop', 'stop'),
    'switch-branch': ((Choice(False, 'n', 'No, leave it pinned'), Choice(True, 'y', 'Yes, follow {branch}')),
                      False, False),
    'file': (_KEEP + (Choice('edit', 'e', 'Edit both in my editor'), _STOP), 'stop', 'stop'),
    'type-change': (_KEEP + (_STOP,), 'stop', 'stop'),
    'value': (_KEEP + (Choice('edit', 'e', 'Show me the file in my editor{aside}'), _STOP), 'stop', 'stop'),
    'confirm-push': ((Choice(True, 'p', 'Push'), Choice(False, 'n', "Don't push")), False, True),
}


@dataclass(frozen=True)
class Question:
    '''One question `push` asks, as data: the UI renders `title`, the `items` listed under it (and
    `files`, for confirm-push) and the `choices`, and returns one choice's `answer`. Every text is
    already safe to show (`_printable`). The facts (`path`, `index`/`count`, `ref`/`branch`, …) are
    there for a UI or a test that wants them.'''
    kind: str
    title: str
    choices: tuple
    enter: object
    unattended: object
    items: tuple = ()
    files: tuple = ()
    path: str = None
    detail: str = None
    index: int = 0
    count: int = 1
    ref: str = None
    branch: str = None

    def answer(self, key):
        '''The answer a typed key means, else the Enter answer.'''
        return next((c.answer for c in self.choices if c.key == key), self.enter)

    def listing(self, most=20):
        '''The lines to show under the title: the items (at most `most`), then confirm-push's files.'''
        out = list(self.items[:most])
        if len(self.items) > most:
            out.append(f'… and {len(self.items) - most} more')
        if self.files:
            out.append(f'files: {", ".join(self.files[:most])}'
                       + (f' … and {len(self.files) - most} more' if len(self.files) > most else ''))
        return out


def question(kind, *, name, items=(), files=(), path=None, detail=None, index=0, count=1, ref=None,
             branch=None, source=None):
    '''Build the `kind` question (a key of QUESTIONS), with its title worded once for every UI.'''
    name, items, files = _printable(name), tuple(map(_printable, items)), tuple(map(_printable, files))
    path, detail = (_printable(path) if path is not None else None), (_printable(detail) if detail else None)
    choices, enter, unattended = QUESTIONS[kind]
    fill = {'branch': branch or 'its branch', 'aside': ' (sets aside the answers above)' if index else ''}
    choices = tuple(c._replace(label=c.label.format(**fill)) for c in choices)
    if kind == 'include-own':
        title = f'{name}: {_count(len(items), "file")} you edited by hand, not committed — push them too?'
    elif kind == 'overlap':
        what = items[0] if len(items) == 1 else _count(len(items), 'file')
        title = f'{name}: your uncommitted edits to {what} overlap what your other machine pushed'
    elif kind == 'switch-branch':
        title = (f'{name} is pinned to {_printable(ref or "a fixed commit")} — follow {branch} instead, so '
                 f'every push reaches your other machines?')
    elif kind in ('file', 'type-change'):
        title = f'{name}: {path} ({index + 1} of {count}) — {detail}'
    elif kind == 'value':
        title = f'{name}: {path}, setting {index + 1} of {count} — {detail}'
    elif kind == 'confirm-push':
        title = (f'{name}: push {_count(len(items))} to {_printable(source)}?'
                 + (f' — {detail}' if detail else ''))
    else:
        raise KeyError(kind)
    return Question(kind, title, choices, enter, unattended, items, files, path, detail, index, count,
                    ref, branch)


class PushUI:
    '''How `push` asks its questions. This base answers each one unattended — the cautious way: your
    own edits stay out, a tag-pinned primary stays pinned, a conflict stops with your work intact (and
    the push itself goes ahead: the command was the consent). The CLI and the TUI subclass it to ask.'''
    interactive = False                                # may git prompt on the terminal (ssh passphrase)?

    def ask(self, q):                                  # a Question -> one of its choices' answers
        return q.unattended

    def edit(self, path):                              # open a file with conflict markers in an editor
        pass

    def progress(self, text):                          # a short "pushing …" status
        pass


def _count(n, word='change'):
    return f'{n} {word}{"s" if n != 1 else ""}'


def _them(n):
    return 'them' if n != 1 else 'it'


_CONTROL = re.compile(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]')


def _printable(text):
    '''Text from a file or a remote, safe to show in a question: control characters (a terminal
    escape could rewrite the prompt or your clipboard) shown as `\\xNN`, line breaks as ⏎.'''
    text = str(text).replace('\r\n', '\n').replace('\n', ' ⏎ ')
    return _CONTROL.sub(lambda m: f'\\x{ord(m.group()):02x}', text)


def _source_host(source):
    '''The host a source lives on (`github:x/y` -> github.com, `git@host:x/y`, `https://host/x`).'''
    for scheme, host in (('github:', 'github.com'), ('gitlab:', 'gitlab.com')):
        if source.startswith(scheme):
            return host
    m = re.match(r'(?:[a-z+]+://)?(?:[^@/]+@)?([^/:]+)', source)
    return m.group(1) if m else source


# A refused fetch / push: (what git says, in lower case) -> the words for it, with the fix for the host
# it lives on. First match wins: a "denied" 403 must not read as "offline?", and a branch rule's
# `[remote rejected]` is not the `[rejected]` of a race. The words are filled from {name} {host}
# {source} {root} {said} (git's first line) {add_key} (where to add an SSH key) {sign_in}.
_FAILURES = (
    (('permission to', 'denied to', 'error: 403', 'returned error: 403', '[remote rejected]'),
     '{name}: {host} refused the push — your account can\'t write to {source}, or a branch rule there '
     'blocked it ("{said:.120}"). Nothing was pushed. Check it is your own repository (`configsys '
     'plugin set-source {name} …` points at another), then push again.'),
    (('host key verification failed',),
     '{name}: this machine has never connected to {host} over SSH, so the push was not sent. Connect '
     'once from a terminal (`ssh -T git@{host}`, answer yes), then push again.'),
    (('permission denied (publickey)', 'passphrase'),
     '{name}: {host} refused this machine\'s SSH key. Add a key to your account ({add_key}), or load '
     'yours into ssh-agent (`ssh-add`), then push again.'),
    (('authentication failed', 'could not read username', 'terminal prompts disabled',
      'invalid username or password'),
     '{name}: {host} wants you signed in. {sign_in}, then push again.'),
    (('repository not found', 'does not appear to be a git repository'),
     '{name}: {source} doesn\'t exist yet (or you can\'t reach it). Create an empty repository there, '
     'then push again.'),
    (('could not resolve host', 'network is unreachable', 'connection timed out', 'connection refused',
      'unable to access'),
     '{name}: couldn\'t reach {host} — offline? Nothing was pushed; try again later.'),
    (('fetch first', 'non-fast-forward', '[rejected]'),
     '{name}: another machine pushed while this push ran. Nothing was lost — run `configsys plugin '
     'push` again to combine and push.'),
)
_ADD_KEY = {'github.com': '`gh ssh-key add ~/.ssh/id_ed25519.pub`, or GitHub\'s SSH keys page',
            'gitlab.com': '`glab ssh-key add ~/.ssh/id_ed25519.pub`, or GitLab\'s SSH Keys page'}
_SIGN_IN_CLI = {'github.com': ('gh', 'Run `gh auth login` and `gh auth setup-git`'),
                'gitlab.com': ('glab', 'Run `glab auth login`')}


def explain_git_failure(text, *, name, root, source):
    '''A refused fetch or push, in plain words with the fix for the host it lives on (_FAILURES).'''
    import shutil
    t = (text or '').lower()
    said = _printable(next((ln.strip() for ln in (text or '').splitlines() if ln.strip()), 'git failed'))
    host = _source_host(source)
    cli = _SIGN_IN_CLI.get(host)
    facts = {'name': name, 'host': host, 'source': source, 'root': root, 'said': said,
             'add_key': _ADD_KEY.get(host, f'your account settings on {host}'),
             'sign_in': cli[1] if cli and shutil.which(cli[0]) else
             'Set up an SSH key, or a git credential helper with a token'}
    words = next((w for needles, w in _FAILURES if any(n in t for n in needles)),
                 '{name}: git said "{said:.160}" (in {root}).')
    return words.format(**facts)


def _err(r, most=160):
    '''What a failed git run said, trimmed for a one-line note.'''
    return ((r.stderr or r.stdout or '') if r is not None else '').strip()[:most]


def _intact(name, root, branch):
    return (f'{name}: nothing was pushed, and your work is committed here as it was. To finish by '
            f'hand: `cd {root} && git pull --rebase origin {branch}`, settle the files git names, '
            f'`git rebase --continue`, then `git push`.')


def _primary(ctx):
    '''(decls, decl, name, root) for the primary, or None.'''
    from . import plugins
    decls = plugins.declared(ctx.paths.user_config_file)
    name = plugins.primary_name(decls)
    if not name:
        return None
    decl = next(d for d in decls if d.get('primary') and plugins.dir_name(d['source']) == name)
    return decls, decl, name, Path(ctx.paths.plugins_dir) / name


def push(ctx, ui=None):
    '''Publish the primary: commit (your own edits only if you say so), fetch, replay this machine's
    commits on top of the remote's, show what will leave and push to its branch. Returns (ok, [lines]).
    Every question is a `Question` passed to `ui.ask` — a conflict per key in a `.hu` file, per file
    otherwise; anything left unsettled ends with nothing pushed and your work intact. Nothing happens
    under --pretend (it previews instead). The steps are `_PushSession`'s.'''
    try:
        found = _primary(ctx)
    except Exception as e:                             # noqa: BLE001 — an unreadable config
        return False, [f'could not read your config: {e}']
    if found is None:
        return False, ['you have no primary plugin to push — `configsys plugin init` makes one from '
                       'your local config, `configsys plugin bless <source>` names an existing one.']
    decls, decl, name, root = found
    if getattr(ctx.runner, 'pretend', False):
        return True, _pretend_preview(name, root, decl['source'])
    if not (root / '.git').exists():
        return False, [f'{name} isn\'t synced here yet — `configsys plugin sync` first.'
                       if not root.exists() else f'{name} ({root}) isn\'t a git repository.']
    return _PushSession(ctx, ui or PushUI(), decls, decl, name, root).run()


class _PushSession:
    '''One `plugin push` over the primary's `PrimaryRepo` (primary-23): `STEPS` run in order, each
    returning None to go on, or the (ok, [lines]) that ends the push; `lines` collects what each step
    said on the way.'''

    STEPS = ('remote', 'follow_branch', 'preflight', 'hand_edits', 'fetch', 'overlap', 'incoming',
             'combine', 'confirm_and_send')

    def __init__(self, ctx, ui, decls, decl, name, root):
        self.ctx, self.ui, self.decls, self.decl, self.name, self.root = ctx, ui, decls, decl, name, root
        self.repo = PrimaryRepo(root)
        self.source = decl['source']
        self.lines = []
        self.url = self.branch = self.upstream = None
        self.first, self.ahead, self.behind = False, 0, 0
        self.left_out, self.left_out_at = set(), None  # your edits left out, and the line saying so
        self.head, self.aside = None, {}               # HEAD before the combine; ignored files set aside

    def run(self):
        for step in self.STEPS:
            end = getattr(self, step)()
            if end is not None:
                return end
        raise AssertionError('confirm_and_send always ends the push')

    def end(self, ok, *more):
        return ok, self.lines + list(more)

    def remote(self):
        self.url = self.repo.text('remote', 'get-url', '--push', 'origin')
        if not self.url:
            name = self.name
            return False, [f'{name} has no remote to push to yet. Create an empty repository for it (on '
                           f'GitHub: `gh repo create {name} --private`, or the website), then run '
                           f'`configsys plugin set-source {name} github:<you>/{name}` and push again.']
        self.branch = self.repo.branch()
        return None

    def follow_branch(self):
        '''A tag-pinned primary: offer to follow its branch, so a push reaches your other machines.'''
        if self.branch:
            return None
        from . import plugins
        repo, name, root, ui = self.repo, self.name, self.root, self.ui
        ref = self.decl.get('ref')
        head_ref = repo.text('rev-parse', '--abbrev-ref', 'origin/HEAD')
        target = (head_ref[len('origin/'):] if head_ref.startswith('origin/') else '') or 'main'
        self.lines.append(f'{name} is pinned to {ref or "a fixed commit"}, so your other machines stay '
                          f'frozen there and a push wouldn\'t reach them (configsys never tags for you).')
        if not ui.ask(question('switch-branch', name=name, ref=ref, branch=target)):
            return self.end(False, f'Left as is. To publish anyway, tag and push it yourself in {root}, '
                                   f'then `configsys plugin update {name} --ref <tag>` on each machine.')
        was = repo.text('rev-parse', 'HEAD')           # switch first; write `ref:` only once it worked
        # through the primary's OWN repo (scrubbed env: never the dotfiles repo a `yadm enter` points
        # GIT_DIR at), the primary alone — not a plugins.sync fan-out that also moved locked
        # transitive plugins (A13 / primary-05)
        why = None
        fetched = _fetch(repo, self.url, ui.interactive)
        if not fetched.ok:
            why = explain_git_failure(fetched.stderr or fetched.stdout, name=name, root=root,
                                      source=self.source)
        elif _verify(self.ctx):
            r = repo.git('log', '--format=%G? %h', f'{was}..origin/{target}')
            if not r.ok or any(ln.strip() and not ln.startswith('G ') for ln in r.stdout.splitlines()):
                why = plugins.sync_note(name, 'unsigned', self.ctx.paths.plugins_dir, primary=True)
        if why is None:
            co = repo.git('checkout', '--quiet', target)
            ff = repo.git('merge', '--ff-only', '--quiet', f'origin/{target}') if co.ok else co
            if not (co.ok and ff.ok):
                why = f'{name}: could not switch to {target} ({_err(ff)}).'
        if why is not None:
            if was and (repo.branch() or repo.text('rev-parse', 'HEAD') != was):
                repo.git('checkout', '--quiet', '--detach', was)   # half switched: back where it was pinned
            return self.end(False, why, f'{name} is still pinned to {ref or "its commit"}; your config '
                                        f'is unchanged.')
        self.decl['ref'] = target
        plugins.set_declared(self.ctx.paths.user_config_file, self.decls)
        self.branch = target
        self.lines.append(f'{name} now follows {target} here; on your other machines run '
                          f'`configsys plugin update {name} --ref {target}` once.')
        return None

    def preflight(self):
        '''What stops a push before anything is touched: a half-done merge / rebase, no committer.'''
        name, root = self.name, self.root
        busy = self.repo.in_progress()
        if busy:
            return self.end(False, f'{name} is in the middle of a {busy}, so nothing was pushed. Finish '
                                   f'it, or `git -C {root} {busy} --abort`, then push again.')
        if not _has_ident(self.ctx, self.repo):        # combining and your edits need a committer
            return self.end(False, f'{name}: no git identity is set, so nothing was pushed — set one (`git '
                                   f'config --global user.name "Your Name"` and `user.email '
                                   f'you@example.com`), then push again.')
        return None

    def hand_edits(self):
        '''Your uncommitted edits: committed if you say so, else left out (and said).'''
        hand_edited = self.repo.dirty() or set()
        if not hand_edited:
            return None
        if self.ui.ask(question('include-own', name=self.name, items=sorted(hand_edited))):
            return self._commit_yours(sorted(hand_edited))
        self.left_out, self.left_out_at = hand_edited, len(self.lines)
        self.lines.append(self._left_out_line())
        return None

    def _left_out_line(self):
        return (f'{self.name}: {_count(len(self.left_out), "file")} with edits of your own left out '
                f'of the push (still here, uncommitted).')

    def _commit_yours(self, paths):
        ok, why = _commit_paths(self.repo, [], paths, 'Edits made by hand',
                                _made_by(self.ctx, 'Included by configsys plugin push'))
        return None if ok else self.end(False, f'{self.name}: could not commit your edits: {why[:160]}')

    def fetch(self):
        self.ui.progress(f'fetching {self.name} …')
        # fetch through the PUSH url (ssh for a github:/gitlab: source), so a private repo you can push
        # to is also one you can fetch from here — the https fetch url may need a sign-in you don't have
        fetched = _fetch(self.repo, self.url, self.ui.interactive)
        if not fetched.ok:
            return self.end(False, explain_git_failure(fetched.stderr or fetched.stdout, name=self.name,
                                                       root=self.root, source=self.source))
        self.upstream = f'origin/{self.branch}'
        self.first = not self.repo.has_ref(self.upstream)
        if self.first:                                 # an empty remote: this is the first push
            self.ahead, self.behind = int(self.repo.text('rev-list', '--count', 'HEAD') or 0), 0
        else:
            self.ahead, self.behind = self.repo.ahead_behind(self.upstream)
        if not self.ahead:
            msg = f'nothing to push — {self.name} has no changes your remote lacks.'
            if self.behind:
                behind = self.behind
                msg += (f' {_count(behind)} from your other machines {"are" if behind != 1 else "is"} '
                        f'waiting; `configsys plugin sync` brings {_them(behind)} in.')
            return self.end(True, msg)
        return None

    def overlap(self):
        '''Left-out edits that overlap what came in: combining would leave conflict markers in them.'''
        if not (self.behind and self.left_out):
            return None
        overlap = sorted(self.left_out & self.repo.incoming(self.upstream))
        if not overlap:
            return None
        name = self.name
        if self.ui.ask(question('overlap', name=name, items=overlap)) != 'include':
            del self.lines[self.left_out_at]
            return self.end(False, f'{name}: your uncommitted edits to {", ".join(overlap)} overlap what '
                                   f'your other machine pushed, so nothing was combined or pushed, and '
                                   f'nothing here changed. Commit or undo them, or push again and include '
                                   f'them.')
        end = self._commit_yours(overlap)
        if end is not None:
            return end
        self.left_out -= set(overlap)                  # included now: the left-out count says the rest
        if self.left_out:
            self.lines[self.left_out_at] = self._left_out_line()
        else:
            del self.lines[self.left_out_at]
        self.ahead, self.behind = self.repo.ahead_behind(self.upstream)
        return None

    def incoming(self):
        '''What may stop the combine, about the commits that came in: each check, in order.'''
        if not self.behind:
            return None
        for check in (self._unsigned_incoming, self._locked):
            line = check()
            if line:
                return self.end(False, line)
        return None

    def _unsigned_incoming(self):
        if not _verify(self.ctx):                      # primary-verify: signed — check before combining
            return None
        r = self.repo.git('log', '--format=%G? %h %s', f'HEAD..{self.upstream}')
        bad = ([_printable(ln[2:]) for ln in r.stdout.splitlines() if ln.strip() and not ln.startswith('G ')]
               if r.ok else ['(could not read them)'])
        if not bad:
            return None
        return (f'{self.name}: your remote has {_count(len(bad), "commit")} without a good signature from a '
                f'key you trust ({"; ".join(bad[:3])}{" …" if len(bad) > 3 else ""}), so nothing was '
                f'combined or pushed (primary-verify: signed). Look at them: `git -C {self.root} log '
                f'--show-signature HEAD..{self.upstream}`.')

    def _locked(self):
        from . import plugins
        if self.name not in plugins.read_locks(getattr(self.ctx.paths, 'plugin_lock_file', None)):
            return None
        # you LOCKED it: the lock holds back what its remote brought in (sync honours it) — a push
        # must not combine those commits in either (review-2026-11-2 A12; pushing when not behind is
        # still fine: nothing comes in)
        return (f'{self.name} is locked — its remote has {_count(self.behind)} you held back, so nothing '
                f'was combined or pushed. `configsys plugin diff {self.name}` shows them; `configsys '
                f'plugin unlock {self.name}` takes them in.')

    def combine(self):
        if not self.behind:
            return None
        repo = self.repo
        self.ui.progress(f'combining {self.name} with your other machines\' changes …')
        self.head = repo.text('rev-parse', 'HEAD')
        # an IGNORED file of yours (a secret a `.cfs/.gitignore` keeps out of git) that the other
        # machine now tracks would be replaced by the combine — or deleted by a Stop, as "not in
        # HEAD". Move it aside first; a Stop / failure / "don't push" puts it back, a push says where
        # it went (A13 / primary-03)
        self.aside = _set_aside(repo, repo.ignored() & repo.incoming(self.upstream))
        ok, more = _combine(self.ctx, self.ui, self.name, repo, self.branch, self.upstream)
        self.lines += more
        if not ok:
            self.lines += _settle_aside(repo, self.name, self.aside, keep_theirs=False)
            return self.end(False)
        self.ahead, _b = repo.ahead_behind(self.upstream)
        if not self.ahead:                             # every change of mine was already there (primary-12)
            self.lines += _settle_aside(repo, self.name, self.aside, keep_theirs=True)
            return self.end(True, f'nothing left to push — your changes were already on {self.name}\'s '
                                  f'remote; what your other machines pushed is combined in here.')
        return None

    def confirm_and_send(self):
        repo, name, root, upstream, first = self.repo, self.name, self.root, self.upstream, self.first
        commits, files = _outgoing(repo, None if first else upstream)
        warn = None
        if _verify(self.ctx) and commits:              # primary-verify: signed — your OWN outgoing ones
            r = repo.git('log', '--format=%G?', *([f'{upstream}..HEAD'] if not first else ['HEAD']))
            unsigned = sum(1 for ln in r.stdout.split() if ln != 'G') if r.ok else 0
            if unsigned:                               # (G5 / primary-21) — they'd be refused elsewhere
                verb = 'is not' if unsigned == 1 else 'are not'
                warn = (f'{unsigned} of these {verb} signed — your other machines (primary-verify: signed) '
                        f'will refuse them; set `commit.gpgsign` in {root}')
        if not self.ui.ask(question('confirm-push', name=name, items=commits, files=files,
                                    source=self.source, detail=warn)):
            return self.end(False, *self._take_back_combine())
        self.lines += _settle_aside(repo, name, self.aside, keep_theirs=True)
        self.ui.progress(f'pushing {name} …')
        pushed = repo.git('push', '--quiet', 'origin', f'HEAD:refs/heads/{self.branch}',
                          env=repo.network_env(self.ui.interactive))
        if not pushed.ok:
            return self.end(False, explain_git_failure(pushed.stderr or pushed.stdout, name=name, root=root,
                                                       source=self.source))
        if first:
            repo.git('branch', '--quiet', f'--set-upstream-to={upstream}')
        return self.end(True, f'pushed {_count(self.ahead)} to {self.source}. Your other machines get '
                              f'{_them(self.ahead)} on their next `configsys plugin sync`.')

    def _take_back_combine(self):
        '''"Don't push" after a combine: put HEAD back where it was before it (`reset --keep`, so
        your uncommitted edits stay) — declining must not leave the other machines' changes checked
        out here, unannounced (primary-13). -> the lines to end with.'''
        name = self.name
        if not self.head or self.repo.text('rev-parse', 'HEAD') == self.head:
            return [f'{name}: not pushed — your changes stay committed here.']
        back = self.repo.git('reset', '--keep', '--quiet', self.head)
        if back.ok:
            return _settle_aside(self.repo, name, self.aside, keep_theirs=False) + [
                f'{name}: not pushed — your changes stay committed here, and what your other machines '
                f'pushed was not combined in (`configsys plugin push` combines it again).']
        return _settle_aside(self.repo, name, self.aside, keep_theirs=True) + [
            f'{name}: not pushed — but what your other machines pushed is combined in here (putting it '
            f'back failed: {_printable(_err(back))}); `git -C {self.root} reset --keep {self.head[:12]}` '
            f'takes it back.']


# -- seeing and undoing configsys's own commits (review-2026-11 G2: `plugin log` / `plugin undo`, Plugins `H`) --

_MADE_BY = 'Made by configsys'                         # the body line of every configsys edit commit


@dataclass(frozen=True)
class Change:
    '''One commit on the primary's branch: `pushed` — your remote has it; `by_configsys` — an edit
    configsys made (not yours, not a combine), so `undo` may take it back.'''
    sha: str
    short: str
    date: str
    subject: str
    files: tuple
    pushed: bool
    by_configsys: bool
    machine: str = ''          # the machine whose configsys made it ("Made by configsys on laptop.")


def history(ctx, n=10):
    '''(name, [Change], newest first) for the last `n` commits on the primary's branch, or None (no
    synced primary on a branch). Local only — "pushed" is as of the last fetch.'''
    try:
        found = _primary(ctx)
        if found is None or not (found[3] / '.git').exists():
            return None
        name, repo = found[2], PrimaryRepo(found[3])
        branch = repo.branch()
        if not branch:
            return None
        upstream = f'origin/{branch}'
        unpushed = set((repo.text('rev-list', 'HEAD', f'^{upstream}') if repo.has_ref(upstream)
                        else repo.text('rev-list', 'HEAD')).split())
        changes = []
        for sha, short, date, parents, subject, body, names in _log(repo, n):
            m = re.search(re.escape(_MADE_BY) + r' on (.+?)\.?$', body, re.M)
            changes.append(Change(sha, short, date, _printable(subject), tuple(map(_printable, names)),
                                  sha not in unpushed,
                                  _MADE_BY in body and len(parents.split()) == 1,
                                  _printable(m.group(1)) if m else ''))
        return name, changes
    except Exception:                                  # noqa: BLE001 — best-effort, never a crash
        return None


def _log(repo, n):
    '''[(sha, short, date, parents, subject, body, (files…))] for the last `n` commits — ONE `git log`
    (primary-19: not a `diff-tree` per commit). With `-z` every record and file name ends in NUL, which
    no commit message or file name can hold, and each file comes as a `:<modes> <blobs> <status>`
    token then its name — so a header is any token in a token's place that isn't one, and a body
    holding `\\x1e` / `\\x1f` (the old separators, remote-controlled) splits nothing. Files as
    `diff-tree --root -r` listed them: a merge lists none. (No `--no-abbrev`: it would make `%h` the
    full sha too; the raw lines' abbreviated blob ids are never read.)'''
    out = repo.git('log', f'-n{int(n)}', '-z', '--raw', '--no-renames', '--root', '--no-show-signature',
                   '--format=%H %h %as %P%n%s%n%b')
    recs, toks, i = [], out.out.split(b'\0') if out.ok else [], 0
    while i < len(toks):
        tok = toks[i]
        if recs and tok.lstrip(b'\n').startswith(b':'):     # one changed file: its raw line, its name
            if i + 1 < len(toks) and toks[i + 1]:
                recs[-1][-1].append(os.fsdecode(toks[i + 1]))
            i += 2
            continue
        i += 1
        head, _nl, rest = tok.decode('utf-8', 'surrogateescape').lstrip('\n').partition('\n')
        fields = head.split(' ')
        if len(fields) < 3:                            # the trailing empty token
            continue
        subject, _nl, body = rest.partition('\n')
        recs.append((fields[0], fields[1], fields[2], ' '.join(fields[3:]), subject, body, []))
    return [r[:-1] + (tuple(r[-1]),) for r in recs]


def undoable(changes):
    '''The newest change configsys made (what `undo` takes back), or None.'''
    return next((c for c in changes if c.by_configsys), None)


def undo(ctx, confirm=None):
    '''Take back the newest edit configsys committed to the primary. Not pushed yet and the last
    commit: it is simply dropped (`git reset --keep`, so your uncommitted edits stay; the reflog still
    has it). Otherwise it is reverted by a new commit, "Undo: <what it did>" — which is itself
    undoable, so undo twice is redo. Refused while you have uncommitted edits to its files, or staged
    changes, or the primary is mid-merge. `confirm(change)` may say no. (ok, [lines]).'''
    found = history(ctx, 50)
    if found is None:
        return False, ['you have no synced primary plugin on a branch — nothing to undo.']
    name, changes = found
    change = undoable(changes)
    if change is None:
        return False, [f'{name}: none of the last {len(changes)} commits is an edit configsys made — '
                       f'nothing to undo.']
    if getattr(ctx.runner, 'pretend', False):
        how = 'drop' if (change is changes[0] and not change.pushed) else 'revert'
        return True, [f'[pretend] would {how} {change.short} {change.subject} ({", ".join(change.files)}) '
                      f'— saving any file it added under <state>/undo/{change.short}/ first']
    repo = PrimaryRepo(_primary(ctx)[3])
    busy = repo.in_progress()
    if busy:
        return False, [f'{name} is in the middle of a {busy} — finish it, or `git -C {repo.root} {busy} '
                       f'--abort`, then undo again.']
    yours = sorted((repo.dirty() or set()) & set(change.files))
    staged = repo.text('diff', '--cached', '--name-only')
    if yours or staged:
        what = ', '.join(yours) if yours else 'changes staged by hand'
        return False, [f'{name}: you have uncommitted edits ({what}), so "{change.subject}" was not '
                       f'undone — commit or undo them first.']
    if confirm is not None and not confirm(change):
        return False, [f'{name}: left as is.']
    # a commit that ADDED files (`plugin init` moving your dotfiles/glue in, a capture) — undoing it
    # takes them out of the primary, and their local copies were moved in, not copied: save them
    # first so the undo never deletes the only copy (A13 / primary-08)
    saved = _save_added(ctx, repo, change)
    if change is changes[0] and not change.pushed:
        r = repo.git('reset', '--keep', '--quiet', 'HEAD~1')
        if not r.ok:
            return False, [f'{name}: could not undo "{change.subject}": {_err(r)}']
        return True, [f'{name}: undid "{change.subject}" ({change.short}) — it was never pushed, so it is '
                      f'simply gone (`git -C {repo.root} reflog` still has it).'] + saved
    if not _has_ident(ctx, repo):
        return False, [_no_ident(name, repo.root)]
    r = repo.git('revert', '--no-commit', change.sha)
    if not r.ok:
        repo.git('revert', '--abort')
        return False, [f'{name}: "{change.subject}" can\'t be undone cleanly — later changes build on '
                       f'it ({_err(r)}). Nothing changed.']
    c = repo.git('commit', '--quiet', '--no-verify', '-m', f'Undo: {change.subject}', '-m', _made_by(ctx))
    if not c.ok:
        repo.git('revert', '--abort')
        return False, [f'{name}: could not commit the undo: {_err(c)}']
    return True, [f'{name}: undid "{change.subject}" ({change.short}) with a new commit, '
                  f'"Undo: {change.subject}"' + ('' if not change.pushed else ' — `plugin push` shares it.')
                  ] + saved


def _save_added(ctx, repo, change):
    '''Copy the files `change` ADDED, as committed, to `<state>/undo/<short sha>/<path>` -> the note
    lines ([] when it added none).'''
    r = repo.git('diff-tree', '--no-commit-id', '--name-only', '-r', '-z', '--diff-filter=A', change.sha)
    added = [os.fsdecode(p) for p in (r.out.split(b'\0') if r.ok else []) if p]
    if not added:
        return []
    dest = Path(ctx.paths.state_dir) / 'undo' / change.short
    for rel in added:
        blob = repo.git('show', f'{change.sha}:{rel}')
        if not blob.ok:
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob.out)
    return [f'  the {len(added)} file(s) it added leave the primary — a copy of each is saved in {dest}']


def _outgoing(repo, upstream):
    '''([commit lines], [files]) that a push would send: what HEAD has that `upstream` lacks (every
    commit and file when there is no upstream yet).'''
    span = [f'{upstream}..HEAD'] if upstream else ['HEAD']
    log = repo.git('log', '--format=%h %s', *span)
    commits = [ln for ln in log.stdout.splitlines() if ln.strip()] if log.ok else []
    diff = (repo.git('diff', '--name-only', '-z', f'{upstream}...HEAD') if upstream
            else repo.git('ls-tree', '-r', '--name-only', '-z', 'HEAD'))
    files = sorted(os.fsdecode(p) for p in diff.out.split(b'\0') if p) if diff.ok else []
    return commits, files


def _pretend_preview(name, root, source):
    '''What `plugin push` would send, as of the last fetch — read-only (no fetch, no commit).'''
    tag = '[pretend]'
    if not (root / '.git').exists():
        return [f'{tag} {name} isn\'t synced here — nothing would be pushed']
    repo = PrimaryRepo(root)
    branch = repo.branch()
    if not branch:
        return [f'{tag} {name} is pinned to a tag or commit — a push would offer to follow its branch first']
    upstream = f'origin/{branch}'
    has_up = repo.has_ref(upstream)
    commits, files = _outgoing(repo, upstream if has_up else None)
    if not commits:
        return [f'{tag} {name}: nothing to push (as of the last fetch) — nothing sent']
    behind = repo.ahead_behind(upstream)[1] if has_up else 0
    out = [f'{tag} would push {_count(len(commits))} to {source} (as of the last fetch'
           + (f'; {_count(behind)} from your other machines would be combined first' if behind else '')
           + '):']
    out += [f'{tag}   {_printable(c)}' for c in commits[:20]]
    out += [f'{tag}   files: {", ".join(_printable(f) for f in files[:20])}'
            + (f' … and {len(files) - 20} more' if len(files) > 20 else '')]
    return out + [f'{tag} nothing sent']


def _merge_driver(repo):
    '''(git -c options, notes file) that make `humerge` git's merge driver for `*.hu` for one command —
    nothing is configured permanently. The attributes file carries your own global one along; the
    driver appends what's worth telling you to the notes file.'''
    import sys
    tmp = _scratch(repo)
    attrs = tmp / 'attributes'
    own = repo.text('config', '--path', 'core.attributesFile')
    own = Path(own) if own else \
        Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'git' / 'attributes'
    try:
        prior = own.read_text(encoding='utf-8') if own.is_file() else ''
    except OSError:
        prior = ''
    attrs.write_text(prior + ('\n' if prior and not prior.endswith('\n') else '') + '*.hu merge=configsys\n',
                     encoding='utf-8')
    notes = tmp / 'notes'
    notes.write_text('', encoding='utf-8')
    # Git runs the driver from the top of the primary's work tree, and `python -m` would put that
    # directory first on sys.path — so a `subprocess.py` or `configsys/` committed to the primary by
    # whoever can push to its remote would run as you. Isolated mode (-I: no cwd, no PYTHON* env,
    # no user site) plus an explicit path to this configsys keeps every import ours.
    pkg = str(Path(__file__).resolve().parent.parent)
    boot = (f'import sys; sys.path.insert(0, {pkg!r}); from configsys.humerge import main; '
            f'sys.exit(main(sys.argv[1:]))')
    command = (f'{shlex.quote(sys.executable)} -I -c {shlex.quote(boot)} '
               f'{shlex.quote(str(notes))} %O %A %B %P %L')
    return ['-c', 'merge.configsys.name=configsys .hu merge', '-c', f'merge.configsys.driver={command}',
            '-c', f'core.attributesFile={attrs}'], notes


def _scratch(repo):
    '''configsys's scratch dir inside the primary's git dir (a gitlink `.git` file — a worktree or
    submodule primary — resolved by git), removed again when the combine ends.'''
    gd = repo.text('rev-parse', '--absolute-git-dir')
    tmp = (Path(gd) if gd else repo.root / '.git') / 'configsys-merge'
    tmp.mkdir(exist_ok=True)
    return tmp


def _driver_notes(notes):
    '''The merge driver's notes, each once and safe to show: they carry file names and plugin
    sources / refs from the remote, so a terminal escape in one goes out as `\\xNN` (primary-11).'''
    try:
        seen = []
        for ln in notes.read_text(encoding='utf-8', errors='replace').splitlines():
            ln = _printable(ln)
            if ln.strip() and ln not in seen:
                seen.append(ln)
        notes.write_text('', encoding='utf-8')
        return seen
    except OSError:
        return []


def _combine(ctx, ui, name, repo, branch, upstream):
    '''Put this machine's commits on top of the remote's, as one undoable step: your uncommitted
    edits are set aside first (they don't overlap what came in — `push` asked about any that do), and
    on ANY way out that isn't a combined result — a stop, a git failure, an exception, Ctrl-C — HEAD is
    put back, any half-done rebase or merge is undone and your edits come back (an exception is then
    re-raised). Returns (ok, [lines]).'''
    head = repo.text('rev-parse', 'HEAD')
    stashed = None                                     # the stash COMMIT we made (by identity, never stash@{0})
    if repo.dirty():
        before = _stash_top(repo)
        if not repo.git('stash', 'push', '--include-untracked', '--quiet', '-m', 'configsys plugin push').ok:
            return False, [f'{name}: could not set your uncommitted edits aside, so nothing was combined '
                           f'or pushed.']
        after = _stash_top(repo)
        # a "dirty" tree git can't stash (a submodule with untracked content: ` M sub`, exit 0, nothing
        # saved) made no entry — popping stash@{0} then applied and dropped YOUR older stash (A13 /
        # primary-06)
        stashed = after if after and after != before else None
    try:
        ok, lines = _replay(ctx, ui, name, repo, upstream)
    except BaseException:
        _restore(repo, head)
        _unstash(repo, name, stashed)
        raise
    finally:                                           # the driver's notes + copies of your files
        import shutil
        shutil.rmtree(_scratch(repo), ignore_errors=True)
    if not ok:
        _restore(repo, head)
        return False, lines + _unstash(repo, name, stashed) + [_intact(name, repo.root, branch)]
    return True, lines + _unstash(repo, name, stashed)


def _restore(repo, head):
    '''Undo a half-done rebase / merge and put HEAD (and the tree) back at `head`. Your own
    uncommitted edits are in the stash by now, and an ignored file the remote now tracks was moved
    aside by push (_set_aside) — the reset would delete it as "not in HEAD" otherwise.'''
    busy = repo.in_progress()
    if busy in ('rebase', 'merge'):
        repo.git(busy, '--abort')
    if repo.text('rev-parse', 'HEAD') != head or repo.dirty():
        repo.git('reset', '--hard', '--quiet', head)


def _replay(ctx, ui, name, repo, upstream):
    '''The combine itself, on a clean tree. A clean replay is a rebase — with `.hu` files merged key
    by key (`humerge`, so two machines adding picks to their own columns is no conflict). When the
    replay still hits a conflict it is backed out, each conflict is asked about — per key in a `.hu`
    file (a `value` question), per file otherwise (a `file` question) — and the two sides are merged with
    those answers. (ok, [lines]); on not-ok the caller restores.'''
    root = repo.root
    driver_opts, notes = _merge_driver(repo)
    rebased = repo.git(*driver_opts, 'rebase', '--quiet', upstream)
    if rebased.ok:
        return True, [f'{name}: {n}' for n in _driver_notes(notes)]
    conflicted = repo.unmerged()
    repo.git('rebase', '--abort')
    _driver_notes(notes)
    if not conflicted:
        return False, [f'{name}: could not combine with the remote: {_printable(_err(rebased))}']
    merged = repo.git(*driver_opts, 'merge', '--no-ff', '--no-commit', '--quiet', upstream)
    conflicted = repo.unmerged() if not merged.ok else []
    if not merged.ok and not conflicted:
        return False, [f'{name}: could not combine with the remote: {_printable(_err(merged))}']
    renamed = _type_renames(repo, conflicted, upstream)   # `x~HEAD` → x: a file whose type differs
    conflicted = [p for p in conflicted if p not in renamed]
    conflicted += sorted(x for x in set(renamed.values()) if x not in conflicted)   # x became a folder
    for i, path in enumerate(conflicted):
        if path in renamed.values():                   # asked once, settled as one file
            twin = next(r for r, p in renamed.items() if p == path)
            if not _settle_type_change(ui, name, repo, path, twin, i, len(conflicted)):
                return False, []
            continue
        settled = _settle_hu(ui, name, repo, path, i, len(conflicted))
        if settled == 'done':
            continue
        choice = settled or ui.ask(question('file', name=name, path=path, detail=_what_changed(repo, path),
                                            index=i, count=len(conflicted)))
        if choice in ('mine', 'theirs'):
            _take(repo, path, 'ours' if choice == 'mine' else 'theirs')
            if _hu_problem(root / path):                # a side's lines can still leave broken humon
                return False, [f'{name}: {path} does not read as humon after taking that side '
                               f'({_hu_problem(root / path)}) — nothing was pushed']
        elif choice == 'edit':
            for _attempt in range(3):                   # a typo would be pushed to every machine,
                ui.edit(root / path)                    # which then skips the file (G5 / primary-14)
                why = 'conflict markers left' if _has_markers(root / path) else _hu_problem(root / path)
                if not why:
                    break
                if not ui.ask(question('file', name=name, path=path, detail=f'it does not parse: {why}',
                                       index=i, count=len(conflicted))) == 'edit':
                    choice = 'stop'
                    break
            else:
                choice = 'stop'
            if choice == 'edit':
                repo.git('add', '-A', paths=[path])
        if choice not in ('mine', 'theirs', 'edit'):
            return False, []
    machine = _machine(ctx)
    combined = repo.git('commit', '--quiet', '--no-edit', '-m',
                        f'Combine {name} changes{f" from {machine}" if machine else ""} with the remote')
    if not combined.ok:
        return False, [f'{name}: could not commit the combined result: {_err(combined)}']
    lines = [f'{name}: {n}' for n in _driver_notes(notes)]
    if conflicted:
        lines.append(f'{name}: combined — {", ".join(map(_printable, conflicted))} settled as you chose.')
    return True, lines


def _type_renames(repo, conflicted, upstream=None):
    '''{`x~<side>`: x} for the files git renamed because the two sides gave `x` different types — a
    file on one, a symlink or submodule on the other ("CONFLICT (distinct types)", `x` conflicted
    too), or a folder ("file/directory": `x` is the other side's folder, merged cleanly). git keeps one
    side under `x` and parks the other under `x~HEAD` / `x~<branch>` (a `/` in the branch spelled
    `_`). Only THAT suffix counts, and only when the two sides' kinds really differ — a real `config~`
    editor backup conflicting beside `config` is an ordinary file conflict (B17 / primary-09).'''
    names = set(conflicted)
    sides = {'HEAD'}
    if upstream:
        sides |= {upstream, upstream.replace('/', '_')}
    out = {}
    for p in conflicted:
        x, _sep, suffix = p.rpartition('~')
        if not x or suffix not in sides:
            continue
        folder = (repo.root / x).is_dir() and not (repo.root / x).is_symlink()
        if not (x in names or folder):
            continue
        if not folder:
            ents = repo.unmerged_entries([x, p])
            kinds = {_kind(e) for side in ents.values() for k, e in side.items() if k in (2, 3) and e}
            if len(kinds) < 2:                         # same kind on both sides: not a type change
                continue
        out[p] = x
    return out


_KINDS = {'120000': 'link', '160000': 'submodule', '040000': 'folder'}


def _kind(entry):
    return _KINDS.get(entry[0], 'file') if entry else None


def _settle_type_change(ui, name, repo, path, twin, i, n):
    '''`path` has a different type on each side (git parked one under `twin`): ask which to keep, as
    one question about `path`, and put that side's entry — its type included — back at `path`, with
    `twin` gone. False = stop.'''
    entries = repo.unmerged_entries([path, twin])
    stage = lambda k: entries.get(path, {}).get(k) or entries.get(twin, {}).get(k)   # noqa: E731
    base, mine, theirs = stage(1), stage(2), stage(3)
    folder = path not in entries and (repo.root / path).is_dir()
    if folder:                                         # one side's folder sits at `path`
        mine, theirs = mine or ('040000', None), theirs or ('040000', None)
    km, kt = _kind(mine), _kind(theirs)
    if km is None or kt is None:                       # not the shape git leaves for distinct types
        return False
    if _kind(base) == km:
        what = f'this machine changed the {km}; your other machine made it a {kt}'
    elif _kind(base) == kt:
        what = f'this machine made it a {km}; your other machine changed the {kt}'
    else:
        what = f'this machine has a {km} there; your other machine has a {kt}'
    choice = ui.ask(question('type-change', name=name, path=path, detail=what, index=i, count=n))
    keep = {'mine': mine, 'theirs': theirs}.get(choice)
    if keep is None:
        return False
    if folder and keep[0] == '040000':                 # keep the folder: drop the parked file
        repo.git('rm', '--quiet', '-f', '--ignore-unmatch', paths=[twin])
        return True
    if folder:                                         # keep the file: the folder's tracked files go
        repo.git('rm', '-r', '--quiet', '-f', '--ignore-unmatch', paths=[path])
    repo.git('rm', '--quiet', '--cached', '-f', '--ignore-unmatch', paths=[path, twin])
    for p in (twin, path):                             # only the two names git wrote — never a folder
        f = repo.root / p
        if f.is_symlink() or f.is_file():
            f.unlink()
    repo.git('update-index', '--add', '--cacheinfo', f'{keep[0]},{keep[1]},{path}')
    repo.git('checkout-index', '--force', '--', path)
    return True


def _settle_hu(ui, name, repo, path, i, n):
    '''A conflicted `.hu` file, key by key: each key both machines changed differently is asked about
    (a `value` question, numbered key k of this file's conflicts — a k past 0 means earlier keys were
    answered, which "show me the file" sets aside, the UI says). Returns 'done' (merged and staged),
    'edit' / 'stop' (the answer for the whole file), or None (not a file this can merge: ask about
    the whole file).'''
    from . import humerge
    if not path.endswith('.hu'):
        return None
    base, mine, theirs = (_stage_text(repo, path, k) for k in (1, 2, 3))
    if mine is None or theirs is None:
        return None
    try:
        res = humerge.merge(base or '', mine, theirs)
        if res.conflicts:                              # can it write the answered file at all? Probe
            humerge.merge(base or '', mine, theirs,    # first, or a failure after the per-key answers
                          {c.path: 'mine' for c in res.conflicts})   # asks the whole file again
    except Exception:                                  # noqa: BLE001 — Unmergeable, or a malformed
        return None                                    # text humerge can't read: the file question
    answers = {}
    for k, c in enumerate(res.conflicts):             # numbered by key within this file
        choice = ui.ask(question('value', name=name, path=path, detail=c.words(), index=k,
                                 count=len(res.conflicts)))
        if choice not in ('mine', 'theirs'):
            return choice if choice == 'edit' else 'stop'
        answers[c.path] = choice
    if answers:
        try:
            res = humerge.merge(base or '', mine, theirs, answers)
        except Exception:                              # noqa: BLE001
            return None
    if res.text is None:
        return None
    text = res.text
    if '\r\n' in mine:                                 # keep the file's own line ending (as the driver does)
        text = text.replace('\r\n', '\n').replace('\n', '\r\n')
    (repo.root / path).write_bytes(text.encode('utf-8'))
    repo.git('add', paths=[path])
    return 'done'


def _set_aside(repo, paths):
    '''Move each of `paths` (ignored files of yours) to a free `<path>.pre-configsys[.N]` -> {path: backup}.'''
    out = {}
    for rel in sorted(paths):
        src = repo.root / rel
        if not (src.is_file() or src.is_symlink()):
            continue
        dst, n = src.with_name(src.name + '.pre-configsys'), 0
        while dst.exists() or dst.is_symlink():
            n += 1
            dst = src.with_name(f'{src.name}.pre-configsys.{n}')
        os.replace(src, dst)
        out[rel] = dst
    return out


def _settle_aside(repo, name, aside, *, keep_theirs):
    '''After the combine: on success the other machine's tracked copy stays and yours is named; on a
    stop / failure (HEAD restored, the path ignored again) yours goes back exactly where it was.'''
    lines = []
    for rel, dst in aside.items():
        src = repo.root / rel
        if keep_theirs and (src.exists() or src.is_symlink()):
            lines.append(f'{name}: {rel} is now tracked by your other machine — its copy is in place; '
                         f'yours (it was ignored here) is kept as {dst.name}.')
        elif not (src.exists() or src.is_symlink()):
            os.replace(dst, src)
    return lines


def _hu_problem(path):
    '''Why `path` (a .hu file) doesn't parse as humon, or None (not a .hu file / it reads fine).'''
    if not str(path).endswith('.hu'):
        return None
    try:
        from .layers import read_tree
        read_tree(path)
        return None
    except Exception as e:                             # noqa: BLE001
        return str(e).split(': ', 1)[-1][:120]


def _stash_top(repo):
    r = repo.git('rev-parse', '-q', '--verify', 'refs/stash')
    return r.stdout.strip() if r.ok else None


def _unstash(repo, name, stashed):
    '''Bring your set-aside edits back — the stash commit `_combine` made, by identity. If they don't
    apply cleanly, the tree is reset to the committed result (no conflict markers left lying around)
    and they stay safe in the stash.'''
    if not stashed:
        return []
    if repo.git('stash', 'apply', '--quiet', stashed).ok:
        listing = repo.git('stash', 'list', '--format=%H')
        shas = listing.stdout.split() if listing.ok else []
        if stashed in shas:                            # drop exactly that entry, wherever it sits
            repo.git('stash', 'drop', '--quiet', f'stash@{{{shas.index(stashed)}}}')
        return []
    repo.git('reset', '--hard', '--quiet')
    return [f'{name}: your uncommitted edits don\'t apply cleanly over the combined result, so they are '
            f'kept in git\'s stash — `git -C {repo.root} stash pop` brings them back to settle.']


def _stage_text(repo, path, n):
    '''A stage as text, or None (absent — or binary / not UTF-8: then it's settled by side).'''
    raw = repo.stage(n, path)
    try:
        return None if raw is None else raw.decode('utf-8')
    except UnicodeDecodeError:
        return None


def _what_changed(repo, path):
    '''What each side did to a conflicted file, in words.'''
    mine, theirs = repo.stage(2, path), repo.stage(3, path)
    if mine is None:
        return 'this machine deleted it; your other machine changed it'
    if theirs is None:
        return 'this machine changed it; your other machine deleted it'
    if repo.stage(1, path) is None:
        return 'both machines created it, differently'
    return 'both machines changed the same lines'


def _take(repo, path, side):
    '''Settle `path` toward one side: changes that don't overlap come from both sides; where they
    overlap, `side` wins. A side that deleted the file deletes it.'''
    base, mine, theirs = (repo.stage(n, path) for n in (1, 2, 3))
    keep = mine if side == 'ours' else theirs
    if keep is None:
        repo.git('rm', '--quiet', paths=[path])
        return
    if base is not None and mine is not None and theirs is not None:
        tmp = _scratch(repo)
        for n, data in (('base', base), ('mine', mine), ('theirs', theirs)):
            (tmp / n).write_bytes(data)
        merged = repo.git('merge-file', '-p', f'--{side}', str(tmp / 'mine'), str(tmp / 'base'),
                          str(tmp / 'theirs'))
        if merged.ok:                                  # with --ours/--theirs no conflict is left
            (repo.root / path).write_bytes(merged.out)
            repo.git('add', paths=[path])
            return
    repo.git('checkout', f'--{side}', paths=[path])
    repo.git('add', paths=[path])


def _has_markers(path):
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return False
    # an `=======` alone is a Markdown underline, not a conflict — only the outer markers count
    return any(ln.startswith(('<<<<<<< ', '>>>>>>> ')) for ln in text.splitlines())


# public spellings of the phrase/identity helpers the CLI and TUI share (F4: no reach-ins)
count_phrase = _count
them_phrase = _them
machine_name = _machine
