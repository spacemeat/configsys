'''primarygit.py — commit configsys's own edits to your primary plugin, locally (docs/done/
primary-push-plan.md, phase 1), and publish them (`push`, phases 3–4).

Every CLI command and every TUI action that may write is bracketed: `snapshot()` records which paths
in the primary's checkout are already dirty, and `commit()` afterwards commits exactly the paths that
became dirty in between — with a message saying what was done. So configsys's edits land as small,
undoable commits on the primary's branch (ready for `plugin push`), while edits you were making by
hand are never swept in: a file that already had uncommitted changes of yours is left for you to
commit, and you're told.

Nothing happens under --pretend, when there's no primary, when it isn't a git checkout, or when it
isn't on a branch (a tag-pinned primary is frozen; its edits stay uncommitted, noted once). With no
git identity configured, the commit uses a repo-local fallback (`<user>@<host>`), noted once. The
bracket is best-effort: whatever goes wrong in it is a note, never a crash of the command.

Every git call goes through `PrimaryRepo` (docs/todo/primary-safety-plan.md): argv lists, never a
shell; bytes in and `os.fsdecode` out, so a file name that isn't UTF-8 is just a name; literal
pathspecs, passed on stdin, so a `[` in a name is no glob and a long list no overflow; and an env
without git's repository-locating variables, so a `GIT_DIR` from a vcsh / yadm session can't send a
commit to another repository.
'''

import getpass
import hashlib
import os
import shlex
import socket
import subprocess
from pathlib import Path


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


class PrimaryRepo:
    '''The one way this module runs git on the primary's checkout at `root`.'''

    def __init__(self, root):
        self.root = Path(root)

    def env(self):
        return _scrub(os.environ, _locating_vars())

    def network_env(self, interactive):
        '''The env for fetch / push. Interactive (the CLI on a terminal): git may ask for a passphrase.
        Otherwise it never prompts: no terminal prompt, no credential-manager popup, and ssh in
        BatchMode — appended to YOUR ssh command ($GIT_SSH_COMMAND, else core.sshCommand, else ssh),
        so a key or proxy you configured there keeps working.'''
        env = self.env()
        if interactive:
            return env
        env.update(GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never')
        ssh = os.environ.get('GIT_SSH_COMMAND') or self.config('core.sshCommand') or 'ssh'
        env['GIT_SSH_COMMAND'] = ssh if 'BatchMode' in ssh else f'{ssh} -o BatchMode=yes'
        return env

    def git(self, *args, paths=None, env=None, input=None):
        '''Run `git <args>` in the primary. `paths` go as a NUL-separated pathspec list on stdin
        (`--pathspec-from-file`), never on the command line.'''
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
        '''The set of paths with uncommitted changes (tracked or untracked), or None.'''
        r = self.git('--no-optional-locks', 'status', '--porcelain', '-z', '--untracked-files=all')
        if not r.ok:
            return None
        out, parts = set(), r.out.split(b'\0')
        i = 0
        while i < len(parts):
            entry = parts[i]
            if len(entry) > 3:
                out.add(os.fsdecode(entry[3:]))
                if entry[:1] in (b'R', b'C'):          # a rename/copy carries its source next
                    i += 1
            i += 1
        return out

    def unmerged(self):
        r = self.git('diff', '--name-only', '--diff-filter=U', '-z')
        return sorted(os.fsdecode(p) for p in r.out.split(b'\0') if p) if r.ok else []

    def stage(self, n, path):
        '''The bytes of `path` at merge stage `n` (1 base, 2 ours, 3 theirs), or None.'''
        r = self.git('show', f':{n}:{path}')
        return r.out if r.ok else None

    def in_progress(self):
        ''''merge' / 'rebase' / 'cherry-pick' / 'revert' when the checkout is in the middle of one
        (yours, or one an interrupted configsys left), else None.'''
        for marker, what in (('MERGE_HEAD', 'merge'), ('rebase-merge', 'rebase'),
                             ('rebase-apply', 'rebase'), ('CHERRY_PICK_HEAD', 'cherry-pick'),
                             ('REVERT_HEAD', 'revert')):
            p = self.text('rev-parse', '--git-path', marker)
            if p and (Path(p) if os.path.isabs(p) else self.root / p).exists():
                return what
        return None

    def incoming(self, upstream):
        '''The paths `upstream` changed since it and HEAD diverged.'''
        r = self.git('diff', '--name-only', '-z', f'HEAD...{upstream}')
        return {os.fsdecode(p) for p in r.out.split(b'\0') if p} if r.ok else set()


class Snapshot:
    def __init__(self, root, name, dirty):
        self.root, self.name, self.dirty = root, name, dirty
        self.committed = False                                # set when commit() made a commit
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


def snapshot(ctx):
    '''What's already dirty in the primary before an edit, or None when configsys won't commit (or
    can't tell — the bracket never stops a command).'''
    try:
        pr = primary_root(ctx)
        if pr is None:
            return None
        dirty = PrimaryRepo(pr[0]).dirty()
        return Snapshot(pr[0], pr[1], dirty) if dirty is not None else None
    except Exception:                                  # noqa: BLE001 — best-effort, never a crash
        return None


def _note_once(ctx, key, text, notes):
    seen = ctx.__dict__.setdefault('_primarygit_noted', set())
    if key not in seen:
        seen.add(key)
        notes.append(text)


def commit(ctx, snap, message):
    '''Commit the paths that became dirty since `snap`, as `message`. Returns a list of notes to show
    (empty when there was nothing to commit or it went through quietly). Never raises.'''
    if snap is None:
        return []
    try:
        return _commit(ctx, snap, message)
    except Exception as e:                             # noqa: BLE001 — best-effort, never a crash
        return [f'could not commit to {snap.name}: {e}']


def _commit(ctx, snap, message):
    repo = PrimaryRepo(snap.root)
    busy = repo.in_progress()
    if busy:                                           # never stage into a half-done merge / rebase
        return [f'could not commit to {snap.name}: it is in the middle of a {busy} — finish it, or '
                f'`git -C {snap.root} {busy} --abort`, and configsys commits again from then on.']
    now = repo.dirty()
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
    if not repo.branch():
        _note_once(ctx, 'detached', f'{snap.name} is pinned to a tag or commit, so configsys saved '
                   f'your changes there but did not commit them (a primary normally follows its '
                   f'branch; see `configsys plugin list`).', notes)
        return notes
    ok, why = _commit_paths(repo, _ident(ctx, repo, snap.name, notes), changed, message,
                            f'Made by configsys on {_host()}.', hooks=False)
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
        return False, add.stderr.strip()[:200]
    c = repo.git(*ident, 'commit', '-q', *([] if hooks else ['--no-verify']), '-m', subject, '-m', body,
                 paths=paths)
    return c.ok, (c.stderr or c.stdout).strip()[:200]


def _host():
    return socket.gethostname() or 'this machine'


def _ident(ctx, repo, name, notes):
    '''`-c user.name=… -c user.email=…` args when git has no identity for the primary (a repo-local
    fallback, `<user>@<host>`, noted once), else [].'''
    if repo.config('user.email'):
        return []
    user, host = getpass.getuser(), socket.gethostname() or 'localhost'
    _note_once(ctx, 'ident', f'no git identity is set, so commits to {name} are signed '
               f'{user}@{host} — set yours with `git config --global user.name/user.email`.', notes)
    return ['-c', f'user.name={user}', '-c', f'user.email={user}@{host}']


# -- where the primary stands (phase 2: the Plugins row, the header chip, `plugin list`) ----------

def state(ctx):
    '''{name, branch, ahead, behind, dirty} for the primary against its remote branch (as of the last
    fetch), or None (no primary, not a git checkout, not on a branch, no remote, --pretend). A primary
    whose remote has never had that branch counts every commit as not pushed yet. Local and cheap.'''
    try:
        pr = primary_root(ctx)
        if pr is None:
            return None
        repo = PrimaryRepo(pr[0])
        branch = repo.branch()
        if not branch:
            return None
        if repo.has_ref(f'origin/{branch}'):
            ahead, behind = repo.ahead_behind(f'origin/{branch}')
        elif repo.text('remote', 'get-url', '--push', 'origin'):
            ahead, behind = int(repo.text('rev-list', '--count', 'HEAD') or 0), 0   # never pushed
        else:
            return None
        return {'name': pr[1], 'branch': branch, 'ahead': ahead, 'behind': behind,
                'dirty': bool(repo.dirty())}
    except Exception:                                  # noqa: BLE001 — best-effort, never a crash
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
    if st['ahead']:
        out.append(f'↑{st["ahead"]}')
    if st['behind']:
        out.append(f'↓{st["behind"]}')
    if st['dirty']:
        out.append('●')
    return ' '.join(out)


def chip(st, *, hide_ahead=False):
    '''The header chip text, or '' when there's nothing to push or sync. `hide_ahead` (under
    `primary-push: auto` / `auto-on-quit`, where configsys pushes for you) leaves out the ↑ part.'''
    ahead = 0 if hide_ahead or not st else st['ahead']
    if not st or not (ahead or st['behind']):
        return ''
    parts = []
    if ahead:
        parts.append(f'↑{st["ahead"]} to push')
    if st['behind']:
        parts.append(f'↓{st["behind"]} to sync')
    return f'{st["name"]}: ' + ', '.join(parts)


def describe(st):
    '''Where the primary stands, in words (for `plugin list`), or '' when it's level and clean.'''
    if not st:
        return ''
    parts = []
    if st['ahead']:
        parts.append(f'{st["ahead"]} change{"s" if st["ahead"] != 1 else ""} not pushed yet '
                     f'(`plugin push` shares {"them" if st["ahead"] != 1 else "it"})')
    if st['behind']:
        parts.append(f'{st["behind"]} change{"s" if st["behind"] != 1 else ""} from your other '
                     f'machines (as of the last fetch) — `plugin sync` brings them in')
    if st['dirty']:
        parts.append('edits not committed yet')
    if st['ahead'] and st['behind']:
        parts.append('both sides changed — `plugin push` combines them')
    return '; '.join(parts)


# -- publishing it (phase 3: `configsys plugin push`, the Plugins `P` key, the `primary-push` setting) --

PUSH_MODES = ('ask', 'auto', 'auto-on-quit', 'manual')


def push_mode(ctx):
    '''The `primary-push` setting: 'ask' (default), 'auto', 'auto-on-quit' or 'manual'.'''
    try:
        return ctx.config.primary_push()
    except Exception:                                  # noqa: BLE001 — a fake/odd ctx: the default
        return 'ask'


class PushUI:
    '''How `push` asks its questions. This base answers every one the cautious way (no prompt): your
    own edits stay out, a tag-pinned primary stays pinned, a conflict stops with your work intact. The
    CLI and the TUI subclass it to ask.'''
    interactive = False                                # may git prompt on the terminal (ssh passphrase)?

    def include_own(self, name, paths):                # your uncommitted edits: push them too?
        return False

    def overlapping(self, name, paths):                # edits left out that overlap what came in
        return 'stop'                                  #   -> 'include' (commit + push them) | 'stop'

    def switch_to_branch(self, name, ref, branch):     # a tag-pinned primary: follow `branch` instead?
        return False

    def resolve(self, name, path, what, i, n):         # -> 'mine' | 'theirs' | 'edit' | 'stop'
        return 'stop'

    def resolve_value(self, name, path, words, i, n):  # one key both changed -> 'mine' | 'theirs' |
        return 'stop'                                  #   'edit' (the whole file) | 'stop'

    def edit(self, path):                              # open a file with conflict markers in an editor
        pass

    def progress(self, text):                          # a short "pushing …" status
        pass


def _count(n, word='change'):
    return f'{n} {word}{"s" if n != 1 else ""}'


def explain_git_failure(text, *, name, root, source):
    '''A refused fetch or push, in plain words with the fix.'''
    import shutil
    t = (text or '').lower()
    first = next((ln.strip() for ln in (text or '').splitlines() if ln.strip()), 'git failed')
    if 'host key verification failed' in t:
        return (f'{name}: this machine has never connected to that host over SSH, so the push was not '
                f'sent. Connect once from a terminal (`ssh -T git@github.com`, answer yes), then push again.')
    if 'permission denied (publickey)' in t or 'passphrase' in t:
        return (f'{name}: the remote refused this machine\'s SSH key. Add a key to your account '
                f'(`gh ssh-key add ~/.ssh/id_ed25519.pub`, or the website\'s SSH keys page), or load '
                f'yours into ssh-agent (`ssh-add`), then push again.')
    if ('authentication failed' in t or 'could not read username' in t
            or 'terminal prompts disabled' in t or 'invalid username or password' in t):
        if shutil.which('gh'):
            return (f'{name}: the remote wants you signed in. Run `gh auth login` and `gh auth '
                    f'setup-git`, then push again.')
        return (f'{name}: the remote wants you signed in. Set up an SSH key, or a git credential '
                f'helper with a token, then push again.')
    if 'repository not found' in t or 'does not appear to be a git repository' in t:
        return (f'{name}: {source} doesn\'t exist yet (or you can\'t reach it). Create an empty '
                f'repository there, then push again.')
    if ('could not resolve host' in t or 'unable to access' in t or 'network is unreachable' in t
            or 'connection timed out' in t or 'connection refused' in t):
        return f'{name}: couldn\'t reach {source} — offline? Nothing was pushed; try again later.'
    if 'fetch first' in t or 'non-fast-forward' in t or '[rejected]' in t:
        return (f'{name}: another machine pushed while this push ran. Nothing was lost — run '
                f'`configsys plugin push` again to combine and push.')
    return f'{name}: git said "{first[:160]}" (in {root}).'


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
    commits on top of the remote's, push to its branch. Returns (ok, [lines]). A conflict is asked about
    per file (`ui.resolve`); anything left unsettled ends with nothing pushed and your work intact.
    Nothing happens under --pretend.'''
    from . import plugins
    ui = ui or PushUI()
    try:
        found = _primary(ctx)
    except Exception as e:                             # noqa: BLE001 — an unreadable config
        return False, [f'could not read your config: {e}']
    if found is None:
        return False, ['you have no primary plugin to push — `configsys plugin init` makes one from '
                       'your local config, `configsys plugin bless <source>` names an existing one.']
    decls, decl, name, root = found
    if getattr(ctx.runner, 'pretend', False):
        return True, [f'[pretend] would commit, combine and push {name} — nothing sent']
    if not (root / '.git').exists():
        return False, [f'{name} isn\'t synced here yet — `configsys plugin sync` first.'
                       if not root.exists() else f'{name} ({root}) isn\'t a git repository.']
    repo = PrimaryRepo(root)
    lines = []
    url = repo.text('remote', 'get-url', '--push', 'origin')
    if not url:
        return False, [f'{name} has no remote to push to yet. Create an empty repository for it (on '
                       f'GitHub: `gh repo create {name} --private`, or the website), then run '
                       f'`configsys plugin set-source {name} github:<you>/{name}` and push again.']
    source = decl['source']
    branch = repo.branch()
    if not branch:
        ref = decl.get('ref')
        target = plugins.default_branch(ctx.runner, root) or 'main'
        lines.append(f'{name} is pinned to {ref or "a fixed commit"}, so your other machines stay '
                     f'frozen there and a push wouldn\'t reach them (configsys never tags for you).')
        if not ui.switch_to_branch(name, ref, target):
            return False, lines + [f'Left as is. To publish anyway, tag and push it yourself in {root}, '
                                   f'then `configsys plugin update {name} --ref <tag>` on each machine.']
        decl['ref'] = target
        plugins.set_declared(ctx.paths.user_config_file, decls)
        res = plugins.sync(ctx.runner, ctx.paths.plugins_dir, [decl])
        action = res[0][1] if res else 'failed'
        if action not in ('updated', 'cloned', 'ahead'):
            return False, lines + [plugins.sync_note(name, action, ctx.paths.plugins_dir, primary=True)
                                   or f'{name}: could not switch to {target} ({action}).']
        branch = target
        lines.append(f'{name} now follows {target} here; on your other machines run '
                     f'`configsys plugin update {name} --ref {target}` once.')
    busy = repo.in_progress()
    if busy:
        return False, lines + [f'{name} is in the middle of a {busy}, so nothing was pushed. Finish it, '
                               f'or `git -C {root} {busy} --abort`, then push again.']
    mine, mine_left = repo.dirty() or set(), set()
    if mine:
        if ui.include_own(name, sorted(mine)):
            ok, why = _commit_paths(repo, _ident(ctx, repo, name, lines), sorted(mine),
                                    'Edits made by hand', f'Included by configsys plugin push on {_host()}.')
            if not ok:
                return False, lines + [f'{name}: could not commit your edits: {why[:160]}']
        else:
            lines.append(f'{name}: {_count(len(mine), "file")} with edits of your own left out of the '
                         f'push (still here, uncommitted).')
            mine_left = mine
    ui.progress(f'fetching {name} …')
    # fetch through the PUSH url (ssh for a github:/gitlab: source), so a private repo you can push
    # to is also one you can fetch from here — the https fetch url may need a sign-in you don't have
    f = _fetch(repo, url, ui.interactive)
    if not f.ok:
        return False, lines + [explain_git_failure(f.stderr or f.stdout, name=name, root=root,
                                                   source=source)]
    upstream = f'origin/{branch}'
    first = not repo.has_ref(upstream)
    if first:                                          # an empty remote: this is the first push
        n = repo.text('rev-list', '--count', 'HEAD')
        ahead, behind = int(n or 0), 0
    else:
        ahead, behind = repo.ahead_behind(upstream)
    if not ahead:
        msg = f'nothing to push — {name} has no changes your remote lacks.'
        if behind:
            msg += (f' {_count(behind)} from your other machines {"are" if behind != 1 else "is"} '
                    f'waiting; `configsys plugin sync` brings {"them" if behind != 1 else "it"} in.')
        return True, lines + [msg]
    overlap = sorted(mine_left & repo.incoming(upstream)) if behind and mine_left else []
    if overlap:                                        # combining would leave conflict markers in them
        if ui.overlapping(name, overlap) != 'include':
            return False, lines[:-1] + [
                f'{name}: your uncommitted edits to {", ".join(overlap)} overlap what your other '
                f'machine pushed, so nothing was combined or pushed, and nothing here changed. Commit '
                f'or undo them, or push again and include them.']
        ok, why = _commit_paths(repo, _ident(ctx, repo, name, lines), overlap, 'Edits made by hand',
                                f'Included by configsys plugin push on {_host()}.')
        if not ok:
            return False, lines + [f'{name}: could not commit your edits: {why[:160]}']
        ahead, behind = repo.ahead_behind(upstream)
    if behind:
        ui.progress(f'combining {name} with your other machines\' changes …')
        ok, more = _combine(ctx, ui, name, repo, branch, upstream)
        lines += more
        if not ok:
            return False, lines
        ahead, _b = repo.ahead_behind(upstream)
    ui.progress(f'pushing {name} …')
    p = repo.git('push', '--quiet', 'origin', f'HEAD:refs/heads/{branch}',
                 env=repo.network_env(ui.interactive))
    if not p.ok:
        return False, lines + [explain_git_failure(p.stderr or p.stdout, name=name, root=root,
                                                   source=source)]
    if first:
        repo.git('branch', '--quiet', f'--set-upstream-to={upstream}')
    return True, lines + [f'pushed {_count(ahead)} to {source}. Your other machines get '
                          f'{"them" if ahead != 1 else "it"} on their next `configsys plugin sync`.']


def _merge_driver(repo):
    '''(git -c args, notes file) that make `humerge` git's merge driver for `*.hu` for one command —
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
    boot = (f'import sys; sys.path.insert(0, {pkg!r}); from configsys.humerge import driver; '
            f'sys.exit(driver(*sys.argv[1:6]))')
    drv = (f'{shlex.quote(sys.executable)} -I -c {shlex.quote(boot)} '
           f'{shlex.quote(str(notes))} %O %A %B %P')
    return ['-c', 'merge.configsys.name=configsys .hu merge', '-c', f'merge.configsys.driver={drv}',
            '-c', f'core.attributesFile={attrs}'], notes


def _scratch(repo):
    '''configsys's scratch dir inside the primary's git dir (a gitlink `.git` file — a worktree or
    submodule primary — resolved by git), removed again when the combine ends.'''
    gd = repo.text('rev-parse', '--absolute-git-dir')
    tmp = (Path(gd) if gd else repo.root / '.git') / 'configsys-merge'
    tmp.mkdir(exist_ok=True)
    return tmp


def _driver_notes(notes):
    try:
        seen = []
        for ln in notes.read_text(encoding='utf-8').splitlines():
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
    stashed = False
    if repo.dirty():
        if not repo.git('stash', 'push', '--include-untracked', '--quiet', '-m', 'configsys plugin push').ok:
            return False, [f'{name}: could not set your uncommitted edits aside, so nothing was combined '
                           f'or pushed.']
        stashed = True
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
    uncommitted edits are in the stash by now, so the tree holds nothing of yours to lose.'''
    busy = repo.in_progress()
    if busy in ('rebase', 'merge'):
        repo.git(busy, '--abort')
    if repo.text('rev-parse', 'HEAD') != head or repo.dirty():
        repo.git('reset', '--hard', '--quiet', head)


def _replay(ctx, ui, name, repo, upstream):
    '''The combine itself, on a clean tree. A clean replay is a rebase — with `.hu` files merged key
    by key (`humerge`, so two machines adding picks to their own columns is no conflict). When the
    replay still hits a conflict it is backed out, each conflict is asked about — per key in a `.hu`
    file (`ui.resolve_value`), per file otherwise (`ui.resolve`) — and the two sides are merged with
    those answers. (ok, [lines]); on not-ok the caller restores.'''
    root = repo.root
    ident = _ident(ctx, repo, name, [])
    drv, notes = _merge_driver(repo)
    r = repo.git(*drv, *ident, 'rebase', '--quiet', upstream)
    if r.ok:
        return True, [f'{name}: {n}' for n in _driver_notes(notes)]
    conflicted = repo.unmerged()
    repo.git('rebase', '--abort')
    _driver_notes(notes)
    if not conflicted:
        return False, [f'{name}: could not combine with the remote: {(r.stderr or r.stdout).strip()[:160]}']
    m = repo.git(*drv, *ident, 'merge', '--no-ff', '--no-commit', '--quiet', upstream)
    conflicted = repo.unmerged() if not m.ok else []
    if not m.ok and not conflicted:
        return False, []
    for i, path in enumerate(conflicted):
        settled = _settle_hu(ui, name, repo, path, i, len(conflicted))
        if settled == 'done':
            continue
        choice = settled or ui.resolve(name, path, _what_changed(repo, path), i, len(conflicted))
        if choice in ('mine', 'theirs'):
            _take(repo, path, 'ours' if choice == 'mine' else 'theirs')
        elif choice == 'edit':
            ui.edit(root / path)
            if _has_markers(root / path):
                choice = 'stop'
            else:
                repo.git('add', '-A', paths=[path])
        if choice not in ('mine', 'theirs', 'edit'):
            return False, []
    c = repo.git(*ident, 'commit', '--quiet', '--no-edit', '-m',
                 f'Combine {name} changes from {_host()} with the remote')
    if not c.ok:
        return False, [f'{name}: could not commit the combined result: {(c.stderr or c.stdout).strip()[:160]}']
    lines = [f'{name}: {n}' for n in _driver_notes(notes)]
    if conflicted:
        lines.append(f'{name}: combined — {", ".join(conflicted)} settled as you chose.')
    return True, lines


def _settle_hu(ui, name, repo, path, i, n):
    '''A conflicted `.hu` file, key by key: each key both machines changed differently is asked about
    (`ui.resolve_value`). Returns 'done' (merged and staged), 'edit' / 'stop' (the answer for the
    whole file), or None (not a file this can merge: ask about the whole file).'''
    from . import humerge
    if not path.endswith('.hu'):
        return None
    base, mine, theirs = (_stage_text(repo, path, k) for k in (1, 2, 3))
    if mine is None or theirs is None:
        return None
    try:
        res = humerge.merge(base or '', mine, theirs)
    except Exception:                                  # noqa: BLE001 — Unmergeable, or a malformed
        return None                                    # text humerge can't read: the file question
    answers = {}
    for c in res.conflicts:
        choice = ui.resolve_value(name, path, c.words(), i, n)
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
    (repo.root / path).write_text(res.text, encoding='utf-8')
    repo.git('add', paths=[path])
    return 'done'


def _unstash(repo, name, stashed):
    '''Bring your set-aside edits back. If they don't apply cleanly, the tree is reset to the
    committed result (no conflict markers left lying around) and they stay safe in the stash.'''
    if not stashed:
        return []
    if repo.git('stash', 'pop', '--quiet').ok:
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
        r = repo.git('merge-file', '-p', f'--{side}', str(tmp / 'mine'), str(tmp / 'base'),
                     str(tmp / 'theirs'))
        if r.ok:                                       # with --ours/--theirs no conflict is left
            (repo.root / path).write_bytes(r.out)
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
