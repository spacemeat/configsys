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

    def _defining_root(self, rc):
        '''The `dotfiles/` dir NEXT TO the .hu file that defined the component (`rc.source`) — a
        plugin / user layer ships content alongside its definitions. Falls back to the base repo's
        dotfiles dir when the component carries no source (a hand-built rc in tests). This is the
        LOWEST-precedence content root: a shipped template, if the layer ships one at all.'''
        src_file = getattr(rc, 'source', '') or ''
        if src_file:
            return Path(src_file).parent / 'dotfiles'
        return self.paths.dotfiles_dir if self.paths is not None else Path('dotfiles')

    def _content_roots(self, rc):
        '''Ordered (root, tier) content roots for resolving `src`, highest precedence first:
        the machine-local store, then the primary plugin's dotfiles/, then the defining layer.
        The first two are the USER's own content (capture writes there); the last is a template
        the defining layer may or may not ship. So your captured config always shadows a template,
        and a base component can declare src/dst WITHOUT shipping any content at all.'''
        roots = []
        p = self.paths
        if p is not None:
            for attr in ('user_dotfiles_dir', 'primary_dotfiles_dir'):
                d = getattr(p, attr, None)
                if d is not None:
                    roots.append((Path(d), 'user'))
        roots.append((self._defining_root(rc), 'template'))
        return roots

    def _capture_root(self):
        '''Where `capture` writes your adopted content, and the highest-precedence root the
        search-path reads: the primary plugin's dotfiles/ if one is configured (portable, in git),
        else the machine-local store ~/.config/configsys/dotfiles. So what capture writes is
        exactly what a later install links.'''
        p = self.paths
        if p is not None:
            d = getattr(p, 'primary_dotfiles_dir', None) or getattr(p, 'user_dotfiles_dir', None)
            if d is not None:
                return Path(d)
        return Path('dotfiles')          # degenerate fallback (no paths); tests always pass paths

    def _resolve(self, src, rc):
        '''(resolved_src_path, tier, root) — the first content root that actually HAS `src` wins,
        with tier 'user' or 'template'. If none does, the defining-layer path with tier None: the
        component is UNPOPULATED — declared but no content anywhere (a personal dotfile you haven't
        captured). That is an expected state, not an error: configsys has no opinion on your
        neovim config, it just knows where it goes.'''
        for root, tier in self._content_roots(rc):
            cand = root / src
            if cand.exists():
                return cand, tier, root
        dr = self._defining_root(rc)
        return dr / src, None, dr

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
        '''[(source_path, target_path, absorb_path_or_None)] resolved for this machine — `src`
        resolved through the content search-path (_resolve).'''
        return [(self._resolve(src, rc)[0], self._expand(dst),
                 self._expand(absorb) if absorb else None)
                for _n, src, dst, absorb in self._specs(rc)]

    def spec_states(self, rc):
        '''[(name, target_display, state, src_root, src_rel, here)] for `dotfiles status`.
        state is one of:
          linked    — our symlink is in place (managed & active)
          adopted   — your content exists in a user root; not linked yet (capture done)
          unmanaged — a real on-system file with NO adopted content -> AT RISK on install
          template  — a shipped template exists, not adopted, nothing on-system yet
          empty     — declared, no content anywhere, nothing on-system (a personal dotfile
                      you haven't captured; harmless — install is a no-op until you do).
        (src_root, src_rel) locate the managed content: for content that EXISTS (linked/adopted/
        template) the root it lives in (a user store, or the base <repo> for a template); for
        unmanaged/empty the capture destination (where it WILL land). `here` is True in the former
        case, False when it's prospective. The caller labels the distinct roots.'''
        capture_root = self._capture_root()
        out = []
        for name, src, dst, _absorb in self._specs(rc):
            srcpath, tier, root = self._resolve(src, rc)
            tgt = self._expand(dst)
            if tgt.is_symlink() and os.path.realpath(tgt) == os.path.realpath(srcpath):
                state = 'linked'
            elif tgt.is_symlink() or tgt.exists():        # a real file/dir, or a foreign symlink
                state = 'adopted' if tier == 'user' else 'unmanaged'
            elif tier == 'user':
                state = 'adopted'                         # captured, dst absent -> links cleanly
            elif tier == 'template':
                state = 'template'
            else:
                state = 'empty'
            if state in ('linked', 'adopted', 'template'):
                src_root, here = root, True               # content exists here
            else:
                src_root, here = capture_root, False      # unmanaged/empty -> where capture puts it
            out.append((name, self.display_path(tgt), state, src_root, src, here))
        return out

    def capture_plan(self, rc, force=False):
        '''What `dotfiles capture` WOULD do for this component — pure, no side effects. Per spec,
        (name, dst_path, dest_path, action):
          copy         — dst is a real file/dir; copy it into the store
          skip-linked  — dst is already our managed symlink (nothing to adopt)
          skip-absent  — dst doesn't exist (or a broken symlink) — nothing to adopt
          skip-exists  — the store already holds content for this src (pass force to overwrite)'''
        root = self._capture_root()
        out = []
        for name, src, dst, _absorb in self._specs(rc):
            tgt = self._expand(dst)
            dest = root / src
            srcpath, _tier, _root = self._resolve(src, rc)
            if tgt.is_symlink() and os.path.realpath(tgt) == os.path.realpath(srcpath):
                action = 'skip-linked'
            elif not tgt.exists():                        # absent, or a broken symlink
                action = 'skip-absent'
            elif dest.exists() and not force:
                action = 'skip-exists'
            else:
                action = 'copy'
            out.append((name, tgt, dest, action))
        return out

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

    def _force(self):
        return bool(getattr(self.paths, 'dotfiles_force', False)) if self.paths is not None else False

    def install(self, rc):
        specs = self._specs(rc)
        if not specs:
            return Result('(dotfiles: no link specs in route)', 1)
        force = self._force()
        pairs, blocked = [], []
        for _name, src, dst, absorb in specs:
            srcpath, tier, _root = self._resolve(src, rc)
            tgt = self._expand(dst)
            ab = self._expand(absorb) if absorb else None
            pairs.append((srcpath, tgt, ab))
            # REFUSE to replace a real on-system file/dir with a TEMPLATE the user hasn't adopted.
            # tier 'user' = you captured it -> linking to your own content is safe; tier None =
            # unpopulated -> the shell skips it (nothing to clobber); an `absorb-into` spec has its
            # own safe relocation. So only an un-adopted TEMPLATE over a real dst is blocked.
            ours = tgt.is_symlink() and os.path.realpath(tgt) == os.path.realpath(srcpath)
            if (not force and tier == 'template' and ab is None
                    and (tgt.exists() or tgt.is_symlink()) and not ours):
                blocked.append(tgt)
        if blocked:
            names = ', '.join(self.display_path(b) for b in blocked)
            msg = (f'{names} already exist(s) on-system and configsys did not create it. '
                   f'This is expected — configsys never overwrites dotfiles it doesn\'t manage. '
                   f'To proceed, either:\n'
                   f'- adopt your current file(s) into your config, then install again (the link '
                   f'will point at YOUR content):  configsys dotfiles capture\n'
                   f'- or replace them now, backing up the original to *{BACKUP_SUFFIX}:  '
                   f'install --force')
            return Result('dotfiles: refused (un-adopted target)', 1, stderr=msg, advisory=True)
        lines = ['set -e']
        for src, tgt, absorb in pairs:
            s, t = shlex.quote(str(src)), shlex.quote(str(tgt))
            # UNPOPULATED is not an error: a component may declare src/dst with no content shipped
            # (a personal dotfile awaiting capture). If the source is absent, skip that spec with a
            # note instead of failing — configsys never invents content for you.
            lines.append(f'if [ -e {s} ]; then')
            lines.append(f'  mkdir -p {shlex.quote(str(tgt.parent))}')
            if absorb is not None:
                # a pre-existing real dst is RELOCATED into the loader dir (made executable so
                # the ~/.bash.d loader still sources it) — the user's own file isn't zapped.
                # If the absorb target is already taken, fall back to a plain backup.
                a, ap = shlex.quote(str(absorb)), shlex.quote(str(absorb.parent))
                lines.append(
                    f'  if [ -e {t} ] && [ ! -L {t} ]; then mkdir -p {ap}; '
                    f'if [ -e {a} ]; then mv {t} {t}{BACKUP_SUFFIX}; '
                    f'else mv {t} {a} && chmod +x {a}; fi; fi')
            else:
                lines.append(f'  if [ -e {t} ] && [ ! -L {t} ]; then mv {t} {t}{BACKUP_SUFFIX}; fi')
            lines.append(f'  ln -sfn {s} {t}')
            lines.append(f'else echo "dotfiles: {rc.comp} not populated ({src} absent) — '
                         f'capture to manage {tgt}" >&2; fi')
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
