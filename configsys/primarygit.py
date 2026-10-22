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


def _git(ctx, root, args, env=None):
    return ctx.runner.run(f'git -C {shlex.quote(str(root))} {args}', capture=True, env=env)


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
    ident = _ident(ctx, snap.root, snap.name, notes)
    paths = ' '.join(shlex.quote(p) for p in changed)
    body = f'Made by configsys on {_host()}.'
    add = _git(ctx, snap.root, f'add -A -- {paths}')
    if add is None or not add.ok:
        return notes + [f'could not commit to {snap.name} ({(add.stderr or "").strip() if add else "git"})']
    c = _git(ctx, snap.root, f'{ident}commit -q -m {shlex.quote(message)} -m {shlex.quote(body)} '
                             f'-- {paths}')
    if c is None or not c.ok:
        return notes + [f'could not commit to {snap.name}: '
                        f'{((c.stderr or c.stdout or "") if c else "").strip()[:200]}']
    snap.committed = True
    return notes


def _host():
    return socket.gethostname() or 'this machine'


def _ident(ctx, root, name, notes):
    '''`-c user.name=… -c user.email=… ` when git has no identity for `root` (a repo-local fallback,
    `<user>@<host>`, noted once), else ''.'''
    who = _git(ctx, root, 'config user.email')
    if who is not None and who.ok and (who.stdout or '').strip():
        return ''
    user, host = getpass.getuser(), socket.gethostname() or 'localhost'
    _note_once(ctx, 'ident', f'no git identity is set, so commits to {name} are signed '
               f'{user}@{host} — set yours with `git config --global user.name/user.email`.', notes)
    return f'-c user.name={shlex.quote(user)} -c user.email={shlex.quote(f"{user}@{host}")} '


# -- where the primary stands (phase 2: the Plugins row, the header chip, `plugin list`) ----------

def state(ctx):
    '''{name, branch, ahead, behind, dirty} for the primary against its remote branch (as of the last
    fetch), or None (no primary, not a git checkout, not on a branch, --pretend). Local and cheap.'''
    pr = primary_root(ctx)
    if pr is None:
        return None
    from . import plugins
    bs = plugins.branch_state(ctx.runner, pr[0])
    if bs is None:
        return None
    branch, ahead, behind, dirty = bs
    return {'name': pr[1], 'branch': branch, 'ahead': ahead, 'behind': behind, 'dirty': dirty}


def fetch(ctx):
    '''Fetch the primary's remote (non-interactive, refs only — the working tree is untouched), so
    `state()` can count what your other machines pushed. Best-effort; False if it couldn't.'''
    pr = primary_root(ctx)
    if pr is None:
        return False
    from . import plugins
    r = ctx.runner.run(f'git -C {shlex.quote(str(pr[0]))} fetch --quiet', capture=True,
                       env=plugins._noninteractive_git_env())
    return r is not None and r.ok


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


def _git_env(interactive):
    from . import plugins
    if interactive:
        return None
    env = plugins._noninteractive_git_env()
    env.setdefault('GIT_SSH_COMMAND', 'ssh -o BatchMode=yes')   # no passphrase / host-key prompt
    return env


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
    lines = []
    url = _git(ctx, root, 'remote get-url --push origin')
    if url is None or not url.ok or not (url.stdout or '').strip():
        return False, [f'{name} has no remote to push to yet. Create an empty repository for it (on '
                       f'GitHub: `gh repo create {name} --private`, or the website), then run '
                       f'`configsys plugin set-source {name} github:<you>/{name}` and push again.']
    source = decl['source']
    cur = _git(ctx, root, 'symbolic-ref --short -q HEAD')
    branch = (cur.stdout or '').strip() if cur is not None and cur.ok else ''
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
    mine = _dirty(ctx, root) or set()
    if mine:
        if ui.include_own(name, sorted(mine)):
            ident = _ident(ctx, root, name, lines)
            paths = ' '.join(shlex.quote(p) for p in sorted(mine))
            _git(ctx, root, f'add -A -- {paths}')
            c = _git(ctx, root, f'{ident}commit -q -m {shlex.quote("Edits made by hand")} -m '
                                f'{shlex.quote(f"Included by configsys plugin push on {_host()}.")} -- {paths}')
            if c is None or not c.ok:
                return False, lines + [f'{name}: could not commit your edits: '
                                       f'{((c.stderr or c.stdout or "") if c else "").strip()[:160]}']
        else:
            lines.append(f'{name}: {_count(len(mine), "file")} with edits of your own left out of the '
                         f'push (still here, uncommitted).')
    env = _git_env(ui.interactive)
    ui.progress(f'fetching {name} …')
    # fetch through the PUSH url (ssh for a github:/gitlab: source), so a private repo you can push
    # to is also one you can fetch from here — the https fetch url may need a sign-in you don't have
    f = ctx.runner.run(f'git -C {shlex.quote(str(root))} fetch --quiet --prune '
                       f'{shlex.quote(url.stdout.strip())} "+refs/heads/*:refs/remotes/origin/*"',
                       capture=True, env=env)
    if f is None or not f.ok:
        return False, lines + [explain_git_failure((f.stderr or f.stdout) if f else '', name=name,
                                                   root=root, source=source)]
    upstream = f'origin/{branch}'
    has_up = _git(ctx, root, f'rev-parse --verify --quiet {shlex.quote(upstream)}')
    first = has_up is None or not has_up.ok
    if first:                                          # an empty remote: this is the first push
        n = _git(ctx, root, 'rev-list --count HEAD')
        ahead, behind = int((n.stdout or '0').strip() or 0) if n is not None and n.ok else 0, 0
    else:
        ahead, behind = plugins._ahead_behind(ctx.runner, shlex.quote(str(root)), upstream)
    if not ahead:
        msg = f'nothing to push — {name} has no changes your remote lacks.'
        if behind:
            msg += (f' {_count(behind)} from your other machines {"are" if behind != 1 else "is"} '
                    f'waiting; `configsys plugin sync` brings {"them" if behind != 1 else "it"} in.')
        return True, lines + [msg]
    if behind:
        ui.progress(f'combining {name} with your other machines\' changes …')
        ok, more = _combine(ctx, ui, name, root, branch, upstream)
        lines += more
        if not ok:
            return False, lines
        ahead, _b = plugins._ahead_behind(ctx.runner, shlex.quote(str(root)), upstream)
    ui.progress(f'pushing {name} …')
    p = ctx.runner.run(f'git -C {shlex.quote(str(root))} push --quiet origin '
                       f'{shlex.quote(f"HEAD:refs/heads/{branch}")}', capture=True, env=env)
    if p is None or not p.ok:
        return False, lines + [explain_git_failure((p.stderr or p.stdout) if p else '', name=name,
                                                   root=root, source=source)]
    if first:
        _git(ctx, root, f'branch --quiet --set-upstream-to={shlex.quote(upstream)}')
    return True, lines + [f'pushed {_count(ahead)} to {source}. Your other machines get '
                          f'{"them" if ahead != 1 else "it"} on their next `configsys plugin sync`.']


def _merge_driver(ctx, root):
    '''(git -c options, env) that make `humerge` git's merge driver for `*.hu` for one command —
    nothing is configured permanently. The attributes file carries your own global one along.'''
    import os
    import sys
    tmp = root / '.git' / 'configsys-merge'
    tmp.mkdir(exist_ok=True)
    attrs = tmp / 'attributes'
    own = _git(ctx, root, 'config --path core.attributesFile')
    own = Path((own.stdout or '').strip()) if own is not None and own.ok and (own.stdout or '').strip() \
        else Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'git' / 'attributes'
    try:
        prior = own.read_text(encoding='utf-8') if own.is_file() else ''
    except OSError:
        prior = ''
    attrs.write_text(prior + ('\n' if prior and not prior.endswith('\n') else '') + '*.hu merge=configsys\n',
                     encoding='utf-8')
    notes = tmp / 'notes'
    notes.write_text('', encoding='utf-8')
    pkg = str(Path(__file__).resolve().parent.parent)
    env = dict(os.environ,
               PYTHONPATH=pkg + (os.pathsep + os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else ''))
    drv = f'{shlex.quote(sys.executable)} -m configsys.humerge {shlex.quote(str(notes))} %O %A %B %P'
    opts = (f'-c merge.configsys.name={shlex.quote("configsys .hu merge")} '
            f'-c merge.configsys.driver={shlex.quote(drv)} '
            f'-c core.attributesFile={shlex.quote(str(attrs))} ')
    return opts, env, notes


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


def _combine(ctx, ui, name, root, branch, upstream):
    '''Put this machine's commits on top of the remote's. A clean replay is a rebase — with `.hu`
    files merged key by key (`humerge`, so two machines adding picks to their own columns is no
    conflict). When the replay still hits a conflict it is backed out completely, each conflict is
    asked about — per key in a `.hu` file (`ui.resolve_value`), per file otherwise (`ui.resolve`) —
    and the two sides are merged with those answers. Returns (ok, [lines]).'''
    ident = _ident(ctx, root, name, [])
    drv, env, notes = _merge_driver(ctx, root)
    r = _git(ctx, root, f'{drv}{ident}rebase --quiet --autostash {shlex.quote(upstream)}', env=env)
    if r is not None and r.ok:
        return True, [f'{name}: {n}' for n in _driver_notes(notes)]
    conflicted = _unmerged(ctx, root)
    _git(ctx, root, 'rebase --abort')
    _driver_notes(notes)
    if not conflicted:
        return False, [f'{name}: could not combine with the remote: '
                       f'{((r.stderr or r.stdout or "") if r else "").strip()[:160]}', _intact(name, root, branch)]
    stashed = False
    if _dirty(ctx, root):                              # your own uncommitted edits sit out the merge
        s = _git(ctx, root, f'stash push --include-untracked --quiet -m {shlex.quote("configsys plugin push")}')
        stashed = s is not None and s.ok
    lines = []
    m = _git(ctx, root, f'{drv}{ident}merge --no-ff --no-commit --quiet {shlex.quote(upstream)}', env=env)
    conflicted = _unmerged(ctx, root) if (m is None or not m.ok) else []
    if m is not None and not m.ok and not conflicted:
        _git(ctx, root, 'merge --abort')
        return False, _unstash(ctx, root, name, stashed) + [_intact(name, root, branch)]
    for i, path in enumerate(conflicted):
        settled = _settle_hu(ctx, ui, name, root, path, i, len(conflicted))
        if settled == 'done':
            continue
        choice = settled or ui.resolve(name, path, _what_changed(ctx, root, path), i, len(conflicted))
        if choice in ('mine', 'theirs'):
            _take(ctx, root, path, 'ours' if choice == 'mine' else 'theirs')
        elif choice == 'edit':
            ui.edit(root / path)
            if _has_markers(root / path):
                choice = 'stop'
            else:
                _git(ctx, root, f'add -A -- {shlex.quote(path)}')
        if choice not in ('mine', 'theirs', 'edit'):
            _git(ctx, root, 'merge --abort')
            return False, _unstash(ctx, root, name, stashed) + [_intact(name, root, branch)]
    c = _git(ctx, root, f'{ident}commit --quiet --no-edit -m '
                        f'{shlex.quote(f"Combine {name} changes from {_host()} with the remote")}')
    if c is None or not c.ok:
        _git(ctx, root, 'merge --abort')
        return False, _unstash(ctx, root, name, stashed) + [_intact(name, root, branch)]
    lines += [f'{name}: {n}' for n in _driver_notes(notes)]
    if conflicted:
        lines.append(f'{name}: combined — {", ".join(conflicted)} settled as you chose.')
    return True, lines + _unstash(ctx, root, name, stashed)


def _settle_hu(ctx, ui, name, root, path, i, n):
    '''A conflicted `.hu` file, key by key: each key both machines changed differently is asked about
    (`ui.resolve_value`). Returns 'done' (merged and staged), 'edit' / 'stop' (the answer for the
    whole file), or None (not a file this can merge: ask about the whole file).'''
    from . import humerge
    if not path.endswith('.hu'):
        return None
    base, mine, theirs = (_stage(ctx, root, path, k) for k in (1, 2, 3))
    if mine is None or theirs is None:
        return None
    try:
        res = humerge.merge(base or '', mine, theirs)
        answers = {}
        for c in res.conflicts:
            choice = ui.resolve_value(name, path, c.words(), i, n)
            if choice not in ('mine', 'theirs'):
                return choice if choice == 'edit' else 'stop'
            answers[c.path] = choice
        if answers:
            res = humerge.merge(base or '', mine, theirs, answers)
    except humerge.Unmergeable:
        return None
    if res.text is None:
        return None
    (root / path).write_text(res.text, encoding='utf-8')
    _git(ctx, root, f'add -- {shlex.quote(path)}')
    return 'done'


def _unstash(ctx, root, name, stashed):
    if not stashed:
        return []
    r = _git(ctx, root, 'stash pop --quiet')
    if r is not None and r.ok:
        return []
    return [f'{name}: your uncommitted edits are kept in git\'s stash — `git -C {root} stash pop` '
            f'brings them back.']


def _unmerged(ctx, root):
    r = _git(ctx, root, 'diff --name-only --diff-filter=U -z')
    return sorted(p for p in ((r.stdout or '').split('\0') if r is not None and r.ok else ()) if p)


def _stage(ctx, root, path, n):
    r = _git(ctx, root, f'show {shlex.quote(f":{n}:{path}")}')
    return r.stdout if r is not None and r.ok else None


def _what_changed(ctx, root, path):
    '''What each side did to a conflicted file, in words.'''
    mine, theirs = _stage(ctx, root, path, 2), _stage(ctx, root, path, 3)
    if mine is None:
        return 'this machine deleted it; your other machine changed it'
    if theirs is None:
        return 'this machine changed it; your other machine deleted it'
    if _stage(ctx, root, path, 1) is None:
        return 'both machines created it, differently'
    return 'both machines changed the same lines'


def _take(ctx, root, path, side):
    '''Settle `path` toward one side: changes that don't overlap come from both sides; where they
    overlap, `side` wins. A side that deleted the file deletes it.'''
    q = shlex.quote(path)
    base, mine, theirs = (_stage(ctx, root, path, n) for n in (1, 2, 3))
    keep = mine if side == 'ours' else theirs
    if keep is None:
        _git(ctx, root, f'rm --quiet -- {q}')
        return
    if base is not None and mine is not None and theirs is not None:
        tmp = root / '.git' / 'configsys-merge'
        tmp.mkdir(exist_ok=True)
        for n, text in (('base', base), ('mine', mine), ('theirs', theirs)):
            (tmp / n).write_text(text, encoding='utf-8')
        t = lambda n: shlex.quote(str(tmp / n))
        r = ctx.runner.run(f'git merge-file -p --{side} {t("mine")} {t("base")} {t("theirs")}',
                           capture=True)
        if r is not None and r.ok:
            (root / path).write_text(r.stdout, encoding='utf-8')
            _git(ctx, root, f'add -- {q}')
            return
    _git(ctx, root, f'checkout --{side} -- {q}')
    _git(ctx, root, f'add -- {q}')


def _has_markers(path):
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return False
    return any(ln.startswith(('<<<<<<< ', '>>>>>>> ')) or ln == '=======' for ln in text.splitlines())
