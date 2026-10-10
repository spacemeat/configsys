'''shellguard.py — keep installers from scribbling in your shell rc files.

configsys owns shell integration (the glue layer under ~/.config/<shell>/conf.d/), so an
installer that appends to ~/.bashrc / ~/.zshrc / ~/.profile on install (sdkman, nvm, rustup,
conda, …) is both a surprise and a duplication. The switch (`installer-shell-writes`, default
block) wraps each component install: SNAPSHOT the guarded rc files, run the install, then REVERT
the files to exactly their prior bytes — and hand back what was removed so the op loop can STAGE
it as an inactive glue candidate the user reviews and promotes (never silently activated).

Design (docs/shell-glue.md "The shell-writes guard"; history docs/done/shell-writes-switch.md):
snapshot-revert-ALWAYS rather than passing each installer's opaque "--no-modify-path" flag — we
can't tell what such a flag suppressed, but a byte-diff of the rc files tells us exactly what the
install added. Reverting = writing the snapshot back verbatim, so any edit (append OR in-place)
lands the file exactly as it was; the captured block is the inserted lines, routed to the right
shell by which rc file they came from.

configsys's OWN marker blocks (`# >>> configsys … >>>` … `# <<< configsys … <<<` — the glue
driver's zsh loader, written by `install shell-glue` inside the guard's window) are never an
installer write: they are excluded from the diff and carried through the revert as they stand.

Staged blocks are MACHINE-LOCAL state, `<state>/staged-glue/<shell>/<component>.<ext>` (never in a
plugin tree). `activate` turns one into ordinary USER glue — the `user.d` namespace `configsys glue
add` writes (drivers/glue.py `Glue.add_user_glue`), linked into conf.d in the user band — and
`discard` deletes it. `migrate_legacy` carries blocks staged/activated by the old layout (under the
dotfiles capture root) over to that design.
'''

import difflib
import os
import re
from pathlib import Path

# Guarded rc files (relative to $HOME) and which shell each one feeds. A reverted ~/.bashrc block is
# bash glue; a ~/.zshrc block is zsh glue — routed by this mapping. Extensible.
GUARDED = [('.bashrc', 'bash'), ('.bash_profile', 'bash'), ('.profile', 'bash'),
           ('.zshrc', 'zsh'), ('.zprofile', 'zsh')]

_STAGE_DIR = 'staged-glue'          # under the state dir: <shell>/<component>.<ext> candidates

# A configsys-owned rc block: `# >>> configsys<tag> >>>` … `# <<< configsys<tag> <<<` (the glue
# loader's tag is ` glue`). The tag pairs a begin with its end.
_CS_BEGIN = re.compile(r'^\s*# >>> configsys(?P<tag>(?:\s.*?)?) >>>\s*$')
_CS_END = '# <<< configsys{tag} <<<'

# The header _format_block writes on every captured block — how migrate_legacy recognizes an
# old-layout ACTIVATED block among other files.
_CAPTURE_MARK = '(captured by configsys'


def _read(path):
    try:
        return path.read_text()
    except (FileNotFoundError, IsADirectoryError):
        return None
    except OSError:
        return None


def snapshot(home):
    '''{abs_path_str: content|None} for every guarded rc file (None = absent). Cheap: a handful of
    small text files, read just before an install so the writer is known by diff afterward.'''
    home = Path(home)
    return {str(home / rel): _read(home / rel) for rel, _shell in GUARDED}


def _added_lines(before, after):
    '''The lines `after` has that `before` didn't (inserted/replaced), in order — difflib opcodes so
    a true insertion is captured even when the installer wrote into the middle of the file.'''
    b = (before or '').splitlines()
    a = (after or '').splitlines()
    out = []
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(None, b, a).get_opcodes():
        if tag in ('insert', 'replace'):
            out.extend(a[j1:j2])
    return out


def _split_cs_blocks(text):
    '''(text_without_configsys_blocks, [(tag, block_text)]) — configsys's own marker blocks pulled
    out of an rc file's text, in order. An unterminated begin marker is not a block (kept as text).'''
    if not text:
        return text or '', []
    lines = text.splitlines(keepends=True)
    kept, blocks, i = [], [], 0
    while i < len(lines):
        m = _CS_BEGIN.match(lines[i].rstrip('\n'))
        if m:
            end = _CS_END.format(tag=m.group('tag'))
            j = next((k for k in range(i + 1, len(lines)) if lines[k].strip() == end), None)
            if j is not None:
                blocks.append((m.group('tag'), ''.join(lines[i:j + 1])))
                i = j + 1
                continue
        kept.append(lines[i])
        i += 1
    return ''.join(kept), blocks


def _restore_with_cs_blocks(before, now_blocks):
    '''`before`, with configsys's blocks set to how they stand NOW: a block present in both is
    replaced in place, one only in `before` is dropped, one only in `now` is appended (where the
    glue driver puts a new block). Used when an op changed both configsys's block and other lines.'''
    _rest, before_blocks = _split_cs_blocks(before or '')
    now_by_tag = dict(now_blocks)
    lines = (before or '').splitlines(keepends=True)
    out, i, placed = [], 0, set()
    while i < len(lines):
        m = _CS_BEGIN.match(lines[i].rstrip('\n'))
        if m:
            end = _CS_END.format(tag=m.group('tag'))
            j = next((k for k in range(i + 1, len(lines)) if lines[k].strip() == end), None)
            if j is not None:
                tag = m.group('tag')
                if tag in now_by_tag and tag not in placed:
                    out.append(now_by_tag[tag])
                    placed.add(tag)
                i = j + 1
                continue
        out.append(lines[i])
        i += 1
    text = ''.join(out)
    for tag, block in now_blocks:
        if tag not in placed:
            if text and not text.endswith('\n'):
                text += '\n'
            text += block
    return text if (text or before is not None) else None


def revert_and_capture(home, snap):
    '''Restore each guarded file to its snapshot bytes and return {shell: captured_block_text} for
    the files an install changed. Reverting a file that didn't exist before means removing it if the
    install created it. Files unchanged since the snapshot are left untouched (no capture).
    configsys's own marker blocks are exempt: a change that is ONLY such a block is kept as written
    (no revert, no capture); alongside installer lines, the installer lines are reverted and the
    block is carried through.'''
    home = Path(home)
    shell_of = {str(home / rel): shell for rel, shell in GUARDED}
    per_shell = {}                                  # shell -> [ (filename, [added lines]) ]
    for path_str, before in snap.items():
        path = Path(path_str)
        now = _read(path)
        if now == before:
            continue                                # untouched — nothing to revert or capture
        before_rest, before_blocks = _split_cs_blocks(before)
        now_rest, now_blocks = _split_cs_blocks(now)
        if now is not None and now_rest == before_rest:
            continue                                # only configsys's own block changed — keep it
        added = _added_lines(before_rest, now_rest)
        if added:
            per_shell.setdefault(shell_of[path_str], []).append((path.name, added))
        # revert to exactly the prior state (with configsys's own blocks as they now stand)
        target = before
        if now is not None and (now_blocks or before_blocks):
            target = _restore_with_cs_blocks(before, now_blocks if now is not None else [])
        if target is None:
            try:
                path.unlink()
            except OSError:
                pass
        else:
            path.write_text(target)
    return {shell: _format_block(blocks) for shell, blocks in per_shell.items()}


def _format_block(blocks):
    '''Assemble the captured lines from one shell's rc file(s) into a glue snippet body, each
    source file's block under a `# from ~/<file>` header so the user sees where it came from.'''
    parts = []
    for name, lines in blocks:
        parts.append(f'# from ~/{name} (captured by configsys — installer wanted to write this)')
        parts.extend(lines)
        parts.append('')
    return '\n'.join(parts).rstrip('\n') + '\n'


# -- op-loop orchestration (shared by the CLI _dispatch_op and the TUI execute_plan) --------

_GUARDED_OPS = ('install', 'upgrade', 'set-version')


def arm(paths, config, component, op):
    '''Snapshot the guarded rc files before an installer op, or None when the guard doesn't apply
    (non-installer op, no config, guard off, or component allow-listed). Degrades to None if config
    lacks the accessor (older/stub contexts) — never blocks an install.'''
    if op not in _GUARDED_OPS or config is None:
        return None
    try:
        if not config.guard_shell_writes(component):
            return None
    except AttributeError:
        return None
    return snapshot(paths.home)


def finish(paths, component, snap):
    '''Revert whatever the op wrote back to `snap` and stage the removed block. Returns a one-line
    report (to print) or None when nothing changed / no snapshot was armed.'''
    if snap is None:
        return None
    captured = revert_and_capture(paths.home, snap)
    if not captured:
        return None
    staged = stage(paths, component, captured)
    n = sum(1 for b in captured.values() for ln in b.splitlines()          # the installer's lines,
            if ln.strip() and not (ln.startswith('# from ~/') and _CAPTURE_MARK in ln))   # not headers
    shells = ', '.join(sorted({s for s, _ in staged}) or captured)
    return (f'guarded: reverted {n} line(s) {component} tried to add to your {shells} rc '
            f'(configsys owns shell integration). Staged as inactive glue — review with '
            f'`configsys dotfiles staged`, enable with `configsys dotfiles activate {component}`.')


# -- staging: inactive glue candidates the user reviews + promotes --------

def _ext(shell):
    from .drivers.glue import _SHELL_EXT
    return _SHELL_EXT.get(shell, 'sh')


def stage_dir(paths):
    '''The machine-local staging dir, `<state>/staged-glue/` (holds `<shell>/<component>.<ext>`).'''
    return Path(paths.state_dir) / _STAGE_DIR


def _merge_into(dest, text):
    '''Write `text` to `dest`, or — when `dest` already holds different content — append it, so
    nothing already there is lost. Returns dest.'''
    dest.parent.mkdir(parents=True, exist_ok=True)
    cur = _read(dest)
    if cur is None or not cur.strip():
        dest.write_text(text)
    elif text.strip() not in cur:
        dest.write_text(cur + ('' if cur.endswith('\n') else '\n') + text)
    return dest


def stage(paths, component, per_shell):
    '''Write each shell's captured block to <state>/staged-glue/<shell>/<component>.<ext> (INACTIVE
    — not linked into any conf.d). A later capture for the same component and shell replaces the
    earlier one. Returns [(shell, path)] for what was staged.'''
    out = []
    root = stage_dir(paths)
    for shell, body in sorted(per_shell.items()):
        if not body.strip():
            continue
        path = root / shell / f'{component}.{_ext(shell)}'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        out.append((shell, path))
    return out


def list_staged(paths, migrate=False):
    '''[(component, shell, path)] for every staged candidate, sorted. READ-ONLY by default (safe under
    --pretend): blocks still sitting in the OLD layout (`<capture-root>/staged-glue/<comp>.<shell>.sh`)
    are listed where they are. `migrate=True` first moves those into the state dir (_migrate_staged);
    activate/discard do that themselves, and `migrate_legacy` does it for the CLI.'''
    if migrate:
        _migrate_staged(paths)
    out = []
    root = stage_dir(paths)
    if root.is_dir():
        for shell_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            shell, ext = shell_dir.name, _ext(shell_dir.name)
            for path in sorted(shell_dir.glob(f'*.{ext}')):
                comp = path.name[:-(len(ext) + 1)]
                if comp:
                    out.append((comp, shell, path))
    if not migrate:
        out.extend(_legacy_staged(paths))
    return sorted(out)


def staged_for(paths, component, migrate=False):
    return [(shell, path) for comp, shell, path in list_staged(paths, migrate=migrate)
            if comp == component]


def _glue_driver(paths, runner):
    from .drivers.glue import Glue
    if runner is None:
        from .runner import Runner
        runner = Runner()
    return Glue(runner, paths=paths)


def activate(paths, component, runner=None, local=False):
    '''Promote a component's staged block(s) to ordinary USER glue: each becomes the user.d snippet
    `<component>.<ext>` in the user's glue root (the primary plugin's unless `local`, else the
    local store — exactly where `configsys glue add` writes), linked into
    ~/.config/<shell>/conf.d/ in the user band (`90-<component>.<ext>`), then removed from staging.
    An existing snippet of that name keeps its content; the block is appended (never clobbered).
    Returns [(shell, conf.d_link)] activated.'''
    drv = _glue_driver(paths, runner)
    done = []
    for shell, staged_path in staged_for(paths, component, migrate=True):
        body = _read(staged_path)
        if body is None:
            continue
        _src, link = drv.add_user_glue(component, shell, body, local=local)
        if link is None:
            continue
        try:
            staged_path.unlink()
        except OSError:
            pass
        done.append((shell, link))
    return done


def discard(paths, component):
    '''Drop a component's staged candidate(s) without activating. Returns the count removed.'''
    n = 0
    for _shell, path in staged_for(paths, component, migrate=True):
        try:
            path.unlink()
            n += 1
        except OSError:
            pass
    return n


# -- one-time migration from the old layout (staged/activated under the dotfiles capture root) ------

def _legacy_capture_roots(paths):
    '''The capture roots the old layout staged under: the primary plugin's dotfiles/ (when set) and
    the machine-local dotfiles store.'''
    roots = []
    for attr in ('primary_dotfiles_dir', 'user_dotfiles_dir'):
        d = getattr(paths, attr, None)
        if d is not None and Path(d) not in roots:
            roots.append(Path(d))
    return roots


def _legacy_staged(paths):
    '''[(comp, shell, path)] for blocks still in the old layout — listed in place, nothing moved.'''
    out = []
    for root in _legacy_capture_roots(paths):
        old_dir = root / _STAGE_DIR
        if not old_dir.is_dir() or old_dir == stage_dir(paths):
            continue
        for path in sorted(old_dir.glob('*.sh')):
            comp, _, shell = path.name[:-3].rpartition('.')
            if comp and shell:
                out.append((comp, shell, path))
    return out


def _migrate_staged(paths):
    '''Move blocks the old layout staged at `<capture-root>/staged-glue/<component>.<shell>.sh` to
    `<state>/staged-glue/<shell>/<component>.<ext>` (merging into a same-named block already there,
    never dropping either). Removes the old dir only once it is empty. Returns [(comp, shell, new)].'''
    moved = []
    for root in _legacy_capture_roots(paths):
        old_dir = root / _STAGE_DIR
        if not old_dir.is_dir() or old_dir == stage_dir(paths):
            continue
        for path in sorted(old_dir.glob('*.sh')):
            comp, _, shell = path.name[:-3].rpartition('.')
            text = _read(path)
            if not comp or not shell or text is None:
                continue
            dest = _merge_into(stage_dir(paths) / shell / f'{comp}.{_ext(shell)}', text)
            try:
                path.unlink()
            except OSError:
                continue
            moved.append((comp, shell, dest))
        try:
            old_dir.rmdir()                     # only when empty — anything else stays put
        except OSError:
            pass
    return moved


def migrate_legacy(paths, runner=None):
    '''One-time carry-over of the old staged-glue layout. (1) Staged blocks move to the state dir
    (_migrate_staged). (2) ACTIVATED blocks — `<capture-root>/shell/<shell>/<component>.sh` files
    carrying the guard's capture header — become user glue (`Glue.add_user_glue`; a primary
    capture root's land in the primary glue root, the local store's stay local), their old
    `conf.d/<component>.sh` link is removed when it points at that file, and the old file is removed
    only after its content was written to user glue. Files without the capture header are never
    touched. Returns human-readable lines describing what moved (empty = nothing to do).'''
    notes = [f'moved staged {shell} glue for {comp} to {dest}'
             for comp, shell, dest in _migrate_staged(paths)]
    drv = None
    home = Path(paths.home)
    primary = getattr(paths, 'primary_dotfiles_dir', None)
    for root in _legacy_capture_roots(paths):
        shell_root = root / 'shell'
        if not shell_root.is_dir():
            continue
        local = not (primary is not None and Path(primary) == root)
        for shell_dir in sorted(p for p in shell_root.iterdir() if p.is_dir()):
            shell = shell_dir.name
            for path in sorted(shell_dir.glob('*.sh')):
                text = _read(path)
                if text is None or _CAPTURE_MARK not in text:
                    continue                    # not a guard-activated block — not ours to move
                comp = path.name[:-3]
                if drv is None:
                    drv = _glue_driver(paths, runner)
                old_link = _old_confd(home, shell) / f'{comp}.sh'
                points_here = False
                try:
                    points_here = (old_link.is_symlink()
                                   and os.path.realpath(old_link) == os.path.realpath(path))
                except OSError:
                    pass
                if points_here:                 # drop the old link first so it can't double-load
                    try:
                        old_link.unlink()
                    except OSError:
                        pass
                _src, link = drv.add_user_glue(comp, shell, text, local=local)
                if link is None:
                    continue                    # couldn't write user glue: leave the old file
                try:
                    path.unlink()
                except OSError:
                    pass
                notes.append(f'converted activated {shell} glue for {comp} to user glue -> {link}')
            try:
                shell_dir.rmdir()               # only when empty
            except OSError:
                pass
        try:
            shell_root.rmdir()
        except OSError:
            pass
    return notes


def _old_confd(home, shell):
    # the conf.d dir the old activate linked into (its own map: `nu` -> nushell)
    sub = {'bash': 'bash', 'zsh': 'zsh', 'fish': 'fish', 'nu': 'nushell'}.get(shell, shell)
    return Path(home) / '.config' / sub / 'conf.d'
