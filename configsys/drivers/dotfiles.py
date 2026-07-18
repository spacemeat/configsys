'''dotfiles.py — the dotfiles driver: symlink repo-synced config into place.

A component maps to one or more *link specs*, each `{ src, dst }`:
  * src — a path under a `dotfiles/` directory next to the .hu file that defined the
    component (the base repo, or a plugin / user layer that ships its own content)
  * dst — where it belongs on this machine; may use env vars / ~ for OS-portable
    locations (e.g. `$XDG_CONFIG_HOME/nvim`, which defaults to ~/.config/nvim)

Install symlinks dst -> src (edits flow back to the repo, per the sync design). An
existing non-symlink dst is backed up to `<dst>.pre-configsys` first (no surprises);
uninstall removes our symlink and restores the backup. A component may have many
specs (neovim's whole config, plus stray files), each with its own OS-dependent dst.

User-space only (no sudo); no version — a component is "linked" or not. No native
lock (ledger carries intent).
'''

import os
import re
import shlex
from pathlib import Path

from ..driver import Driver
from ..runner import Result

_VAR = re.compile(r'\$[A-Za-z_][A-Za-z0-9_]*')
BACKUP_SUFFIX = '.pre-configsys'


class DotFiles(Driver):
    name = 'dotfiles'
    privileged = False
    default_scope = 'user'

    # -- specs & paths ----------------------------------------------------

    @staticmethod
    def _specs(rc):
        '''[(name, src, dst, absorb)] link specs. A component may be a single inline spec
        (top-level src/dst) or a set of named specs (config: {src,dst}, ...). `absorb-into` is
        optional: where a PRE-EXISTING real dst is relocated at install (instead of the plain
        `.pre-configsys` backup) so it stays live — e.g. a stray ~/.bash_aliases moved into the
        ~/.bash.d loader dir, where the new one still sources it.'''
        f = rc.fields
        out = []
        if 'src' in f and 'dst' in f:
            out.append((rc.comp, f['src'], f['dst'], f.get('absorb-into')))
        for key, val in f.items():
            if isinstance(val, dict) and 'src' in val and 'dst' in val:
                out.append((key, val['src'], val['dst'], val.get('absorb-into')))
        return out

    def _home(self):
        return self.paths.home if self.paths is not None else Path.home()

    def _env(self):
        return self.paths.env if self.paths is not None else dict(os.environ)

    def _content_root(self, rc):
        '''Where a component's `src:` files live: a `dotfiles/` dir NEXT TO the .hu file that
        defined the component (`rc.source`), so a plugin / user layer ships its own content
        alongside its definitions — the parallel to plugin data files. Falls back to the base
        repo's dotfiles dir when the component carries no source (a hand-built rc in tests).
        For the base repo this is identical to paths.dotfiles_dir (routes.hu sits at repo root).'''
        src_file = getattr(rc, 'source', '') or ''
        if src_file:
            return Path(src_file).parent / 'dotfiles'
        return self.paths.dotfiles_dir if self.paths is not None else Path('dotfiles')

    def _source(self, src, root):
        return root / src

    def _expand(self, dst):
        '''Expand env vars + ~ in a destination against configsys HOME.'''
        env, home = self._env(), self._home()

        def repl(m):
            var = m.group(0)[1:]
            if var == 'XDG_CONFIG_HOME':
                return env.get('XDG_CONFIG_HOME') or str(home / '.config')
            if var == 'XDG_DATA_HOME':
                return env.get('XDG_DATA_HOME') or str(home / '.local/share')
            if var == 'HOME':
                return str(home)
            return env.get(var, m.group(0))

        s = _VAR.sub(repl, str(dst))
        if s == '~':
            return home
        if s.startswith('~/'):
            return home / s[2:]
        return Path(s)

    def _pairs(self, rc):
        '''[(source_path, target_path, absorb_path_or_None)] resolved for this machine.'''
        root = self._content_root(rc)
        return [(self._source(src, root), self._expand(dst),
                 self._expand(absorb) if absorb else None)
                for _n, src, dst, absorb in self._specs(rc)]

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        pairs = self._pairs(rc)
        if not pairs:
            return None
        for src, tgt, _absorb in pairs:
            if not tgt.is_symlink():
                return None
            if os.path.realpath(tgt) != os.path.realpath(src):
                return None
        return 'linked'

    def get_latest(self, rc):
        return None  # dotfiles track the repo; no version notion

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        pairs = self._pairs(rc)
        if not pairs:
            return Result('(dotfiles: no link specs in route)', 1)
        lines = ['set -e']
        for src, tgt, absorb in pairs:
            s, t = shlex.quote(str(src)), shlex.quote(str(tgt))
            lines.append(
                f'test -e {s} || {{ echo "dotfiles source missing: {src}" >&2; exit 1; }}')
            lines.append(f'mkdir -p {shlex.quote(str(tgt.parent))}')
            if absorb is not None:
                # a pre-existing real dst is RELOCATED into the loader dir (made executable so
                # the ~/.bash.d loader still sources it) — the user's own file isn't zapped.
                # If the absorb target is already taken, fall back to a plain backup.
                a, ap = shlex.quote(str(absorb)), shlex.quote(str(absorb.parent))
                lines.append(
                    f'if [ -e {t} ] && [ ! -L {t} ]; then mkdir -p {ap}; '
                    f'if [ -e {a} ]; then mv {t} {t}{BACKUP_SUFFIX}; '
                    f'else mv {t} {a} && chmod +x {a}; fi; fi')
            else:
                lines.append(f'if [ -e {t} ] && [ ! -L {t} ]; then mv {t} {t}{BACKUP_SUFFIX}; fi')
            lines.append(f'ln -sfn {s} {t}')
        return self.runner.run('\n'.join(lines), capture=False)

    def upgrade(self, rc):
        return self.install(rc)  # idempotent re-link

    def set_version(self, rc, version):
        return self.install(rc)

    def uninstall(self, rc):
        pairs = self._pairs(rc)
        if not pairs:
            return Result('(dotfiles: no link specs in route)', 1)
        lines = []
        for _src, tgt, absorb in pairs:
            t = shlex.quote(str(tgt))
            # only remove our own symlink; then put back what we displaced — the absorbed file
            # (relocated original) if there is one, else any plain `.pre-configsys` backup.
            lines.append(f'if [ -L {t} ]; then rm -f {t}; fi')
            if absorb is not None:
                a = shlex.quote(str(absorb))
                lines.append(f'if [ -e {a} ]; then mv {a} {t}; '
                             f'elif [ -e {t}{BACKUP_SUFFIX} ]; then mv {t}{BACKUP_SUFFIX} {t}; fi')
            else:
                lines.append(f'if [ -e {t}{BACKUP_SUFFIX} ]; then mv {t}{BACKUP_SUFFIX} {t}; fi')
        return self.runner.run('\n'.join(lines), capture=False)

    def location(self, rc):
        targets = [self.display_path(tgt) for _src, tgt, _absorb in self._pairs(rc)]
        return '; '.join(targets) if targets else None

    def lock(self, rc):
        return Result('(dotfiles lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(dotfiles unlock recorded in ledger)', 0)
