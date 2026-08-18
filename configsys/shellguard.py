'''shellguard.py — keep installers from scribbling in your shell rc files.

configsys owns shell integration (the glue layer under ~/.config/<shell>/conf.d/), so an
installer that appends to ~/.bashrc / ~/.zshrc / ~/.profile on install (sdkman, nvm, rustup,
conda, …) is both a surprise and a duplication. The switch (`installer-shell-writes`, default
block) wraps each component install: SNAPSHOT the guarded rc files, run the install, then REVERT
the files to exactly their prior bytes — and hand back what was removed so the op loop can STAGE
it as an inactive glue candidate the user reviews and promotes (never silently activated).

Design (docs/shell-writes-switch.md): snapshot-revert-ALWAYS rather than passing each installer's
opaque "--no-modify-path" flag — we can't tell what such a flag suppressed, but a byte-diff of the
rc files tells us exactly what the install added. Reverting = writing the snapshot back verbatim,
so any edit (append OR in-place) lands the file exactly as it was; the captured block is the
inserted lines, routed to the right shell by which rc file they came from.
'''

import difflib
import os
from pathlib import Path

# Guarded rc files (relative to $HOME) and which shell each one feeds. A reverted ~/.bashrc block is
# bash glue; a ~/.zshrc block is zsh glue — routed to shell/<shell>/ by this mapping. Extensible.
GUARDED = [('.bashrc', 'bash'), ('.bash_profile', 'bash'), ('.profile', 'bash'),
           ('.zshrc', 'zsh'), ('.zprofile', 'zsh')]

_STAGE_DIR = 'staged-glue'          # under the capture root; holds <component>.<shell>.sh candidates


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


def revert_and_capture(home, snap):
    '''Restore each guarded file to its snapshot bytes and return {shell: captured_block_text} for
    the files an install changed. Reverting a file that didn't exist before means removing it if the
    install created it. Files unchanged since the snapshot are left untouched (no capture).'''
    home = Path(home)
    shell_of = {str(home / rel): shell for rel, shell in GUARDED}
    per_shell = {}                                  # shell -> [ (filename, [added lines]) ]
    for path_str, before in snap.items():
        path = Path(path_str)
        now = _read(path)
        if now == before:
            continue                                # untouched — nothing to revert or capture
        added = _added_lines(before, now)
        if added:
            per_shell.setdefault(shell_of[path_str], []).append((path.name, added))
        # revert to exactly the prior state
        if before is None:
            try:
                path.unlink()
            except OSError:
                pass
        else:
            path.write_text(before)
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


def _capture_root(paths):
    '''Where staged candidates go: the primary plugin's dotfiles/ if configured, else the machine
    store — matching the dotfiles driver's capture root.'''
    return getattr(paths, 'primary_dotfiles_dir', None) or paths.user_dotfiles_dir


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
    staged = stage(_capture_root(paths), component, captured)
    n = sum(len(b.strip().splitlines()) for b in captured.values())
    shells = ', '.join(sorted({s for s, _ in staged}) or captured)
    return (f'guarded: reverted {n} line(s) {component} tried to add to your {shells} rc '
            f'(configsys owns shell integration). Staged as inactive glue — review with '
            f'`configsys dotfiles staged`, enable with `configsys dotfiles activate {component}`.')


# -- staging: inactive glue candidates the user reviews + promotes --------

def stage_dir(capture_root):
    return Path(capture_root) / _STAGE_DIR


def stage(capture_root, component, per_shell):
    '''Write each shell's captured block to <capture_root>/staged-glue/<component>.<shell>.sh
    (INACTIVE — not linked into any conf.d). Returns [(shell, path)] for what was staged.'''
    out = []
    d = stage_dir(capture_root)
    d.mkdir(parents=True, exist_ok=True)
    for shell, body in sorted(per_shell.items()):
        if not body.strip():
            continue
        path = d / f'{component}.{shell}.sh'
        path.write_text(body)
        out.append((shell, path))
    return out


def list_staged(capture_root):
    '''[(component, shell, path)] for every staged candidate, sorted. Filename is
    <component>.<shell>.sh; a component name may itself contain dots, so split from the right.'''
    d = stage_dir(capture_root)
    if not d.is_dir():
        return []
    out = []
    for path in sorted(d.glob('*.sh')):
        stem = path.name[:-3]                       # strip .sh
        comp, _, shell = stem.rpartition('.')
        if comp and shell:
            out.append((comp, shell, path))
    return out


def staged_for(capture_root, component):
    return [(shell, path) for comp, shell, path in list_staged(capture_root) if comp == component]


def _confd(home, shell):
    # active loader dir, mirroring the dotfiles driver's _SHELL_CONFD map
    sub = {'bash': 'bash', 'zsh': 'zsh', 'fish': 'fish', 'nu': 'nushell'}.get(shell, shell)
    return Path(home) / '.config' / sub / 'conf.d'


def activate(capture_root, component, home):
    '''Promote a component's staged candidate(s) to active glue: move each to the authoring layout
    <capture_root>/shell/<shell>/<component>.sh (executable) and symlink it into
    ~/.config/<shell>/conf.d/<component>.sh so the shell sources it. Removes the staged copy.
    Returns [(shell, confd_link)] activated. Idempotent: re-activating relinks in place.'''
    home = Path(home)
    done = []
    for shell, staged_path in staged_for(capture_root, component):
        author = Path(capture_root) / 'shell' / shell / f'{component}.sh'
        author.parent.mkdir(parents=True, exist_ok=True)
        author.write_text(staged_path.read_text())
        os.chmod(author, os.stat(author).st_mode | 0o111)     # loaders source only executable files
        confd = _confd(home, shell)
        confd.mkdir(parents=True, exist_ok=True)
        link = confd / f'{component}.sh'
        if link.is_symlink() or link.exists():
            try:
                link.unlink()
            except OSError:
                pass
        link.symlink_to(author)
        try:
            staged_path.unlink()
        except OSError:
            pass
        done.append((shell, link))
    return done


def discard(capture_root, component):
    '''Drop a component's staged candidate(s) without activating. Returns the count removed.'''
    n = 0
    for _shell, path in staged_for(capture_root, component):
        try:
            path.unlink()
            n += 1
        except OSError:
            pass
    return n
