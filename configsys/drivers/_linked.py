'''_linked.py — the one link / unlink the config drivers share (dotfiles, glue; review-2026-11-2 D4).

Both drivers place content by symlink. They used to build a shell script each (`ln -sfn` behind a
backup guard, a restore fragment), four copies with four slightly different safety properties. These
two functions are the only way either driver now puts a link in place or takes one away, so the rules
hold everywhere:

`link(runner, src, dst, *, owned_roots=(), absorb=None, ours=None)`
  * dst already resolves to src → nothing to do (that includes a conf.d that is itself a dir link
    into the store, where the store file IS the deployed file — a relink would be a self-loop);
  * a symlink WE own — one resolving inside an `owned_roots` root, or that `ours(dst)` accepts
    when the driver judges ownership itself — is re-pointed;
  * anything else at dst — your real file or dir, or ANOTHER tool's link (stow, chezmoi) — is moved
    aside first: into `absorb` when given and free (made executable; a real file only), else to the
    first free `<dst>.pre-configsys`, `.1`, `.2`, … An earlier backup is never overwritten, and no
    link of someone else's is silently replaced.
`unlink(runner, dst, *, owned_roots=(), absorb=None, ours=None)` -> (outcome, detail)
  * removes dst only when it is a symlink we own (same test); then puts back what we displaced — the absorbed
    file, else `<dst>.pre-configsys` — into the gap it leaves. A real file there (an app that saves by
    replacing our link) or someone else's link is yours and stays.

Both honor --pretend: they echo what they would do and touch nothing. Writes happen in Python (no
shell), and our own link is swapped atomically (a temp link renamed over it).
'''

import os
from collections import namedtuple
from pathlib import Path

from ..runner import Result

BACKUP_SUFFIX = '.pre-configsys'

# One row of a config driver's `spec_states` (the Glue/Dotfiles status views): the spec `name`, its
# `target` (display path), `state` (linked / drifted / template / empty / loader-on / …), the content
# root it comes from + the path inside it, whether that content is `here`, and `kind` (glue / config).
SpecState = namedtuple('SpecState', 'name target state src_root src_rel here kind')


def inside(path, root):
    '''True when `path` resolves (realpath) to `root` or below it.'''
    rp, rr = os.path.realpath(path), os.path.realpath(root)
    return rp == rr or rp.startswith(rr.rstrip(os.sep) + os.sep)


def owned(dst, roots):
    '''True when `dst` is a symlink resolving into one of our content `roots`.'''
    return os.path.islink(dst) and any(inside(dst, r) for r in roots)


def free_backup(path):
    '''The first free `<path>.pre-configsys`, `.pre-configsys.1`, `.2`, … — never an existing backup.'''
    path = Path(path)
    cand, n = path.with_name(path.name + BACKUP_SUFFIX), 0
    while cand.exists() or cand.is_symlink():
        n += 1
        cand = path.with_name(f'{path.name}{BACKUP_SUFFIX}.{n}')
    return cand


def _echo(runner, msg):
    echo = getattr(runner, 'echo', None)
    (echo or print)(msg)


def _occupied(p):
    return p.exists() or p.is_symlink()


def link(runner, src, dst, *, owned_roots=(), absorb=None, ours=None):
    '''Point `dst` at `src` by the rules in the module docstring. -> Result (stdout names anything
    moved aside). `ours(dst)` replaces the owned_roots test when a driver judges ownership itself.'''
    src, dst = Path(src), Path(dst)
    is_ours = ours or (lambda d: owned(d, owned_roots))
    pretend = bool(getattr(runner, 'pretend', False))
    try:
        if _occupied(dst) and os.path.realpath(dst) == os.path.realpath(src):
            return Result(f'link {dst}', 0)                # already in place
        aside = None                                       # where the occupant goes, if anywhere
        if dst.is_symlink():
            if not is_ours(dst):
                aside = free_backup(dst)                   # another tool's link: keep it, don't replace
        elif dst.exists():
            aside = (absorb if (absorb is not None and not _occupied(Path(absorb)) and dst.is_file())
                     else free_backup(dst))
        if pretend:
            if aside is not None:
                _echo(runner, f'[pretend] would move {dst} aside to {aside}')
            _echo(runner, f'[pretend] would link {dst} -> {src}')
            return Result(f'link {dst}', 0, pretended=True)
        dst.parent.mkdir(parents=True, exist_ok=True)
        note = ''
        if aside is not None:
            aside = Path(aside)
            aside.parent.mkdir(parents=True, exist_ok=True)
            os.rename(dst, aside)
            if absorb is not None and aside == Path(absorb):
                aside.chmod(aside.stat().st_mode | 0o111)  # an absorbed file is sourced: executable
            note = f'moved your existing {dst} to {aside}'
        tmp = dst.with_name(f'.{dst.name}.configsys-link')
        if tmp.is_symlink() or tmp.exists():
            tmp.unlink()
        os.symlink(src, tmp)
        os.replace(tmp, dst)                               # atomic over our own old link
        return Result(f'link {dst}', 0, stdout=note)
    except OSError as e:
        return Result(f'link {dst}', 1, stderr=f'could not link {dst} -> {src}: {e.strerror or e}')


def unlink(runner, dst, *, owned_roots=(), absorb=None, ours=None):
    '''Take our link at `dst` away and restore what it displaced. -> (outcome, detail): outcome is
    'removed' (detail: the restored path or None), 'kept' (not our link — detail says what is
    there), 'absent', or 'error' (detail: the message).'''
    dst = Path(dst)
    if not _occupied(dst):
        return 'absent', None
    if not (ours or (lambda d: owned(d, owned_roots)))(dst):
        return 'kept', 'a real file' if not dst.is_symlink() else 'another tool\'s link'
    backup = dst.with_name(dst.name + BACKUP_SUFFIX)
    restore = (Path(absorb) if absorb is not None and _occupied(Path(absorb))
               else backup if _occupied(backup) else None)
    if getattr(runner, 'pretend', False):
        _echo(runner, f'[pretend] would remove the link {dst}'
              + (f' and put {restore} back' if restore is not None else ''))
        return 'removed', restore
    try:
        dst.unlink()
        if restore is not None:
            os.rename(restore, dst)
        return 'removed', restore
    except OSError as e:
        return 'error', f'could not remove the link {dst}: {e.strerror or e}'
