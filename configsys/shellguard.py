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
driver's bash/zsh/elvish/nushell loader blocks, which a glue install inside the guard's window
writes) are never an
installer write: they are excluded from the diff and carried through the revert as they stand.

Staged blocks are MACHINE-LOCAL state, `<state>/staged-glue/<shell>/<component>.<ext>` (never in a
plugin tree). `activate` turns one into ordinary USER glue — the `user.d` namespace `configsys glue
add` writes (drivers/glue.py `Glue.add_user_glue`), linked into conf.d in the user band — and
`discard` deletes it. (The old layout's one-time migration — blocks staged/activated under the
dotfiles capture root — is retired, review-2026-11-2 §7.16.)
'''

import difflib
import os
import re
from pathlib import Path

from . import shells as _shells
from .shells import SHELLS

# Guarded rc files (home-relative, or under $XDG_CONFIG_HOME — shells.expand) and which shell each one feeds. A reverted ~/.bashrc block is
# bash glue; a ~/.zshrc block is zsh glue — routed by this mapping. Every shell configsys supports is
# covered, login and env files included (rustup-style installers write ~/.zshenv; a safety feature
# has uniform coverage or doesn't ship — review-2026-11-2 A15).
GUARDED = [(rel, n) for n, spec in SHELLS.items() for rel in spec.guarded]

# Directories a shell sources EVERY file of, where installers drop a file of their own: a new regular
# file there (never a link — configsys's glue links live there too) is staged and taken back out.
GUARDED_DIRS = [(rel, n) for n, spec in SHELLS.items() for rel in spec.guarded_dirs]

_STAGE_DIR = 'staged-glue'          # under the state dir: <shell>/<component>.<ext> candidates


def _where(entries, home, env):
    '''{abs_path_str: (label, shell)} for GUARDED / GUARDED_DIRS rows: the label is the path relative
    to the home (`.zshrc`, `.config/fish/config.fish`), or absolute when $XDG_CONFIG_HOME is elsewhere.'''
    out = {}
    for rel, shell in entries:
        path = _shells.expand(rel, home, env)
        try:
            label = str(path.relative_to(home))
        except ValueError:
            label = str(path)
        out[str(path)] = (label, shell)
    return out

# A configsys-owned rc block: `# >>> configsys<tag> >>>` … `# <<< configsys<tag> <<<` (the glue
# loader's tag is ` glue`). The tag pairs a begin with its end.
_CS_BEGIN = re.compile(r'^\s*# >>> configsys(?P<tag>(?:\s.*?)?) >>>\s*$')
_CS_END = '# <<< configsys{tag} <<<'


# The header _format_block writes on every captured block (merging skips re-adding it).
_CAPTURE_MARK = '(captured by configsys'


def _read(path):
    '''The file's text, decoded so EVERY byte round-trips (`surrogateescape`, no newline translation)
    — a Latin-1 comment or CRLF line endings in your rc must neither crash the guard nor come back
    altered (dotfiles-glue-13). None when absent/unreadable.'''
    try:
        return path.read_bytes().decode('utf-8', 'surrogateescape')
    except (FileNotFoundError, IsADirectoryError):
        return None
    except OSError:
        return None


def _write(path, text):
    path.write_bytes(text.encode('utf-8', 'surrogateescape'))


class Snapshot(dict):
    '''{abs_path_str: content|None} plus `.ident` {abs_path_str: what the path IS} — a regular file,
    absent, or a symlink to a given target (see _identity) — and the `.env` its paths were expanded in.'''
    ident = None
    dirs = None
    env = None


def _identity(path):
    '''('link', target) | ('file',) | ('absent',) | ('other',) — lstat, never followed.'''
    try:
        if path.is_symlink():
            return ('link', os.readlink(path))
        if path.is_file():
            return ('file',)
        return ('other',) if path.exists() else ('absent',)
    except OSError:
        return ('other',)


def snapshot(home, env=None):
    '''{abs_path_str: content|None} for every guarded rc file (None = absent), and each one's
    identity. Cheap: a handful of small text files, read just before an install so the writer is
    known by diff afterward. `env` supplies $XDG_CONFIG_HOME (default <home>/.config).'''
    home = Path(home)
    files = _where(GUARDED, home, env)
    snap = Snapshot({p: _read(Path(p)) for p in files})
    snap.ident = {p: _identity(Path(p)) for p in files}
    snap.dirs = {p: _listing(Path(p)) for p in _where(GUARDED_DIRS, home, env)}
    snap.env = env
    return snap


def _listing(d):
    try:
        return {e.name for e in Path(d).iterdir()}
    except OSError:
        return set()


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


class Captured(dict):
    '''{shell: captured_block_text}, plus `.linked` — [(label, link target, [added lines])] for each
    guarded file that is a SYMLINK an install wrote through: left exactly as written (reverting would
    write through the link into its target; staging lines still live would double them on activate),
    but named, so the user knows (no surprises).'''

    def __init__(self, *a, linked=None, **kw):
        super().__init__(*a, **kw)
        self.linked = linked or []


def revert_and_capture(home, snap):
    '''Restore each guarded file to its snapshot bytes and return {shell: captured_block_text} for
    the files an install changed (a `Captured`, whose `.linked` names the links written through). Reverting a file that didn't exist before means removing it if the
    install created it. Files unchanged since the snapshot are left untouched (no capture).
    configsys's own marker blocks are exempt: a change that is ONLY such a block is kept as written
    (no revert, no capture); alongside installer lines, the installer lines are reverted and the
    block is carried through.'''
    home = Path(home)
    files = _where(GUARDED, home, getattr(snap, 'env', None))
    shell_of = {p: shell for p, (_label, shell) in files.items()}
    rel_of = {p: label for p, (label, _shell) in files.items()}
    per_shell = {}                                  # shell -> [ (filename, [added lines]) ]
    linked = []                                     # (filename, link target, [added lines])
    idents = getattr(snap, 'ident', None) or {}
    for path_str, before in snap.items():
        path = Path(path_str)
        now = _read(path)
        if now == before:
            continue                                # untouched — nothing to revert or capture
        if path_str in idents and _identity(path) != idents[path_str] \
                and 'link' in (_identity(path)[0], idents[path_str][0]):
            # the path became (or stopped being, or re-pointed) a LINK — a config being linked into
            # place (zsh-dotfiles), not an installer appending lines —
            # and writing the snapshot back would go THROUGH the new link into your captured config
            # (dotfiles-glue-01). Leave it.
            continue
        if path.is_symlink():
            # never write through a link into its target (your captured config) — but say what landed
            added = _added_lines(_split_cs_blocks(before)[0], _split_cs_blocks(now)[0])
            if added:
                try:
                    tgt = os.readlink(path)
                except OSError:
                    tgt = '?'
                linked.append((rel_of[path_str], tgt, added))
            continue
        before_rest, before_blocks = _split_cs_blocks(before)
        now_rest, now_blocks = _split_cs_blocks(now)
        if now is not None and now_rest == before_rest:
            continue                                # only configsys's own block changed — keep it
        added = _added_lines(before_rest, now_rest)
        if added:
            per_shell.setdefault(shell_of[path_str], []).append((rel_of[path_str], added))
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
            _write(path, target)
    dirs = _where(GUARDED_DIRS, home, getattr(snap, 'env', None))
    shell_of_dir = {p: shell for p, (_label, shell) in dirs.items()}
    rel_of_dir = {p: label for p, (label, _shell) in dirs.items()}
    for dir_str, before in (getattr(snap, 'dirs', None) or {}).items():
        for name in sorted(_listing(dir_str) - before):
            f = Path(dir_str) / name
            if f.is_symlink() or not f.is_file():
                continue                            # a link (glue's own, or a tool's) is left alone
            text = _read(f)
            if text is None:
                continue
            per_shell.setdefault(shell_of_dir[dir_str], []).append(
                (f'{rel_of_dir[dir_str]}/{name}', text.splitlines()))
            try:
                f.unlink()                          # taken back out: staged for your review instead
            except OSError:
                pass
    return Captured({shell: _format_block(blocks) for shell, blocks in per_shell.items()},
                    linked=linked)


def _format_block(blocks):
    '''Assemble the captured lines from one shell's rc file(s) into a glue snippet body, each
    source file's block under a `# from ~/<file>` header so the user sees where it came from.'''
    parts = []
    for name, lines in blocks:
        where = name if name.startswith('/') else f'~/{name}'
        parts.append(f'# from {where} (captured by configsys — installer wanted to write this)')
        parts.extend(lines)
        parts.append('')
    return '\n'.join(parts).rstrip('\n') + '\n'


# -- op-loop orchestration (actions.run_plan, which both the CLI and the TUI run) --------

_GUARDED_OPS = ('install', 'upgrade', 'set-version', 'fix-scope')   # (a reinstall too)


_OWN_DRIVERS = frozenset({'dotfiles', 'glue'})       # configsys's own config drivers: not "installers"


def arm(paths, config, component, op, driver=None):
    '''Snapshot the guarded rc files before an installer op, or None when the guard doesn't apply
    (non-installer op, no config, guard off, component allow-listed, or configsys's OWN dotfiles/glue
    driver — linking your zshrc into place is not an installer scribbling in it). Degrades to None if
    config lacks the accessor (older/stub contexts) — never blocks an install.'''
    if op not in _GUARDED_OPS or config is None or driver in _OWN_DRIVERS:
        return None
    try:
        if not config.guard_shell_writes(component):
            return None
    except AttributeError:
        return None
    return snapshot(paths.home, getattr(paths, 'env', None))


def finish(paths, component, snap):
    '''Revert whatever the op wrote back to `snap` and stage the removed block. Returns a one-line
    report (to print) or None when nothing changed / no snapshot was armed.'''
    if snap is None:
        return None
    captured = revert_and_capture(paths.home, snap)
    notes = []
    if captured:
        staged = stage(paths, component, captured)
        n = sum(1 for b in captured.values() for ln in b.splitlines()          # the installer's lines,
                if ln.strip() and not (ln.startswith('# from ') and _CAPTURE_MARK in ln))   # not headers
        shells = ', '.join(sorted({s for s, _ in staged}) or captured)
        notes.append(f'guarded: reverted {n} line(s) {component} tried to add to your {shells} rc '
                     f'(configsys owns shell integration). Staged as inactive glue — review with '
                     f'`configsys dotfiles staged`, enable with `configsys dotfiles activate {component}`.')
    for label, tgt, added in getattr(captured, 'linked', ()):
        where = label if label.startswith('/') else f'~/{label}'
        notes.append(f'guarded: {component} added {len(added)} line(s) to {where}, a link to {tgt} — '
                     f'not reverted (configsys never writes through a link); review them there:'
                     + ''.join(f'\n       {ln}' for ln in added))
    return '\n  -> '.join(notes) or None


# -- staging: inactive glue candidates the user reviews + promotes --------

def _ext(shell):
    spec = SHELLS.get(shell)
    return spec.ext if spec else 'sh'


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


def list_staged(paths):
    """[(component, shell, path)] for every staged candidate, sorted. Read-only (safe under --pretend)."""
    out = []
    root = stage_dir(paths)
    if root.is_dir():
        for shell_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            shell, ext = shell_dir.name, _ext(shell_dir.name)
            for path in sorted(shell_dir.glob(f'*.{ext}')):
                comp = path.name[:-(len(ext) + 1)]
                if comp:
                    out.append((comp, shell, path))
    return sorted(out)


def staged_for(paths, component):
    return [(shell, path) for comp, shell, path in list_staged(paths) if comp == component]


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
    for shell, staged_path in staged_for(paths, component):
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
    for _shell, path in staged_for(paths, component):
        try:
            path.unlink()
            n += 1
        except OSError:
            pass
    return n
