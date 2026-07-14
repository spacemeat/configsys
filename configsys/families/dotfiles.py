'''dotfiles.py — the \\dotfiles family: symlink repo-synced config into place.

A component maps to one or more *link specs*, each `{ src, dst }`:
  * src — a path under the repo's `dotfiles/` directory (the git-synced source)
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

from ..component import Family
from ..runner import Result

_VAR = re.compile(r'\$[A-Za-z_][A-Za-z0-9_]*')
BACKUP_SUFFIX = '.pre-configsys'


class DotFiles(Family):
    name = 'dotfiles'
    privileged = False
    default_scope = 'user'

    # -- specs & paths ----------------------------------------------------

    @staticmethod
    def _specs(rc):
        '''[(name, src, dst)] from the component's nested link-spec fields.'''
        out = []
        for key, val in rc.fields.items():
            if isinstance(val, dict) and 'src' in val and 'dst' in val:
                out.append((key, val['src'], val['dst']))
        return out

    def _home(self):
        return self.paths.home if self.paths is not None else Path.home()

    def _env(self):
        return self.paths.env if self.paths is not None else dict(os.environ)

    def _source(self, src):
        base = self.paths.dotfiles_dir if self.paths is not None else Path('dotfiles')
        return base / src

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
        '''[(source_path, target_path)] resolved for this machine.'''
        return [(self._source(src), self._expand(dst)) for _n, src, dst in self._specs(rc)]

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        pairs = self._pairs(rc)
        if not pairs:
            return None
        for src, tgt in pairs:
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
        for src, tgt in pairs:
            s, t = shlex.quote(str(src)), shlex.quote(str(tgt))
            lines.append(
                f'test -e {s} || {{ echo "dotfiles source missing: {src}" >&2; exit 1; }}')
            lines.append(f'mkdir -p {shlex.quote(str(tgt.parent))}')
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
        for _src, tgt in pairs:
            t = shlex.quote(str(tgt))
            # only remove our own symlink; then restore any backup we made
            lines.append(f'if [ -L {t} ]; then rm -f {t}; fi')
            lines.append(f'if [ -e {t}{BACKUP_SUFFIX} ]; then mv {t}{BACKUP_SUFFIX} {t}; fi')
        return self.runner.run('\n'.join(lines), capture=False)

    def location(self, rc):
        targets = [self._display_path(tgt) for _src, tgt in self._pairs(rc)]
        return '; '.join(targets) if targets else None

    def lock(self, rc):
        return Result('(dotfiles lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(dotfiles unlock recorded in ledger)', 0)
