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

import fnmatch
import os
import re
import shlex
import shutil
from pathlib import Path

from ..driver import Driver
from ..runner import Result

_VAR = re.compile(r'\$[A-Za-z_][A-Za-z0-9_]*')
BACKUP_SUFFIX = '.pre-configsys'

# glue: shell-integration snippets, keyed by shell. `_SHELL_EXT` = the file extension per shell;
# `_SHELL_CONFD` = the active loader dir (uniform ~/.config/<shell>/conf.d/, mirroring fish's native
# one). Repo ships bash variants today; other shells activate the moment their variant exists.
_SHELL_EXT = {'bash': 'sh', 'zsh': 'zsh', 'fish': 'fish', 'nu': 'nu'}
_SHELL_CONFD = {'bash': '~/.config/bash/conf.d', 'zsh': '~/.config/zsh/conf.d',
                'fish': '~/.config/fish/conf.d', 'nu': '~/.config/nushell/conf.d'}
_GLUE_SHELLS = ('bash', 'zsh', 'fish', 'nu')

# config: an app's own user config lives under a `<component>.cfs/` MARKER dir in the content store,
# content keyed by each spec's `src` name; a `manifest.hu` inside records the src->dst layout + the
# exclude list. The dir existing == "configsys manages this config" even before any content (the #5
# managed-when-empty signal). `.gitignore` is generated from excludes so secrets never sync.
CFS_SUFFIX = '.cfs'
MANIFEST_NAME = 'manifest.hu'
# secret-shaped basenames auto-suggested into a fresh manifest's exclude: on first capture — cheap
# insurance so credentials never enter the store (verboten at capture AND git-ignored).
_SECRET_GLOBS = ['.env', '*.env', 'id_*', '*_history', '*.pem', '*.key',
                 'credentials*', '*.secret', 'secrets', '.ssh']

# loader components (`loader: <shell>`): hook a shell up to source its ~/.config/<shell>/conf.d/*.
# fish auto-sources conf.d natively (no rc edit); bash rides the distro ~/.bash_aliases convention
# (bash-dotfiles, kept as-is); zsh needs one configsys-owned, marker-delimited rc block; nu is punted
# (dir only). The markers make the block idempotent + cleanly removable.
_RC_BEGIN = '# >>> configsys glue >>>'
_RC_END = '# <<< configsys glue <<<'
_SHELL_RC = {'zsh': '~/.zshrc'}
# how each rc-driven shell sources its conf.d dir (empty-glob-safe).
_RC_SOURCE = {
    'zsh': ('setopt local_options null_glob\n'
            'for _f in {confd}/*.zsh; do source "$_f"; done\n'
            'unset _f'),
}


class DotFiles(Driver):
    name = 'dotfiles'
    privileged = False
    default_scope = 'user'

    # -- specs & paths ----------------------------------------------------

    def _specs(self, rc):
        '''[(name, src, dst, absorb, kind)] link specs, kind in {config, glue}. A component may mix:
          * a single inline spec (top-level src/dst) -> config;
          * named specs (`config: {src,dst}`, `aliases: {src,dst}`, ...) -> config;
          * GLUE, either top-level `glue: <name>` OR nested (`aliases: { glue: <name> }`) -> one
            spec per shell that has a snippet (src shell/<shell>/<name>.<ext>, with a bash.d/<name>.sh
            fallback for pre-move layers; dst ~/.config/<shell>/conf.d/<name>.<ext>).
        A `config` spec's content lives under a `<component>.cfs/` marker dir; glue under shell/.
        `absorb-into` relocates a pre-existing real dst instead of a plain backup.'''
        f = rc.fields
        out = []
        if 'src' in f and 'dst' in f:
            out.append((rc.comp, f['src'], f['dst'], f.get('absorb-into'), 'config'))
        if f.get('glue'):
            out.extend(self._glue_specs(f['glue'], rc))
        for key, val in f.items():
            if not isinstance(val, dict):
                continue
            if 'src' in val and 'dst' in val:
                out.append((key, val['src'], val['dst'], val.get('absorb-into'), 'config'))
            elif 'glue' in val:                            # nested glue (mixed config+glue component)
                out.extend(self._glue_specs(val['glue'], rc))
        return out

    def _glue_specs(self, glue, rc):
        '''glue specs for a glue name: one per shell that actually ships a snippet.'''
        return [(f'{glue}@{shell}', src, f'{_SHELL_CONFD[shell]}/{glue}.{ext}', None, 'glue')
                for shell, ext, src in self._glue_variants(glue, rc)]

    def _installed_shells(self):
        '''Which shells to ACTIVATE glue for: those whose binary is on PATH (design: per INSTALLED
        shell, NOT $SHELL — $SHELL is only the login shell). Overridable via CONFIGSYS_GLUE_SHELLS
        (comma-separated) for tests / to force a set. Bash is the baseline if nothing is detected,
        so a user is never left with no glue.'''
        env = self._env()
        forced = env.get('CONFIGSYS_GLUE_SHELLS')
        if forced is not None:
            return [s.strip() for s in forced.split(',') if s.strip()]
        found = [s for s in _GLUE_SHELLS if shutil.which(s, path=env.get('PATH'))]
        return found or ['bash']

    def _glue_variants(self, glue, rc):
        '''(shell, ext, src) for each INSTALLED shell that HAS a snippet for this glue name.
        Precedence: the highest content root that carries one wins (so YOUR plugin/store copy beats
        the repo template), and within a root the new `shell/<shell>/<name>.<ext>` path beats the
        pre-move `bash.d/<name>.sh` fallback (bash only). Repo ships bash today; other shells light up
        the moment BOTH their binary is present AND a `shell/<shell>/<name>.<ext>` variant lands.'''
        out = []
        installed = self._installed_shells()
        for shell in _GLUE_SHELLS:
            if shell not in installed:                     # activate only where the shell is present
                continue
            ext = _SHELL_EXT[shell]
            srcs = [f'{shell}/conf.d/{glue}.{ext}',       # store deployed-mirror (materialized copies)
                    f'shell/{shell}/{glue}.{ext}']        # repo/plugin authoring layout
            if shell == 'bash':
                srcs.append(f'bash.d/{glue}.sh')          # legacy plugin/store layout
            chosen = None
            for root, _tier in self._content_roots(rc):   # store, primary plugin, then repo template
                for src in srcs:
                    if (root / src).exists():
                        chosen = src
                        break
                if chosen:
                    break
            if chosen:
                out.append((shell, ext, chosen))
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

    def _resolve(self, src, rc, kind='config'):
        '''(resolved_src_path, tier, root) — the first content root that actually HAS `src` wins,
        with tier 'user' or 'template'. A `config` spec's content sits under that root's
        `<component>.cfs/<src>` marker dir (with a legacy bare `<root>/<src>` fallback so content
        captured before the .cfs layout still links); a `glue` spec's `src` is already a
        root-relative path (`shell/<shell>/x.sh`). If none has it, the defining-layer path with tier
        None: the component is UNPOPULATED — declared but no content anywhere (a personal dotfile you
        haven't captured). That is an expected state, not an error. `root` is always the BASE content
        root (for status labeling); the returned path points inside `.cfs` for config.'''
        for root, tier in self._content_roots(rc):
            if kind == 'config':
                cand = root / f'{rc.comp}{CFS_SUFFIX}' / src
                if cand.exists():
                    return cand, tier, root
                legacy = root / src                        # pre-.cfs capture layout
                if legacy.exists():
                    return legacy, tier, root
            else:
                cand = root / src
                if cand.exists():
                    return cand, tier, root
        dr = self._defining_root(rc)
        if kind == 'config':
            return dr / f'{rc.comp}{CFS_SUFFIX}' / src, None, dr
        return dr / src, None, dr

    # -- config .cfs marker + manifest ------------------------------------

    def _cfs_dir(self, rc, root=None):
        '''The `<component>.cfs/` marker dir under `root` (default: the capture root). Its existence
        is the "managed" signal (#5), independent of whether any content lives inside yet.'''
        base = Path(root) if root is not None else self._capture_root()
        return base / f'{rc.comp}{CFS_SUFFIX}'

    def _marker_present(self, rc):
        '''True if a `.cfs` marker exists in ANY content root — the component is managed even if no
        content or link is in place yet.'''
        for root, _tier in self._content_roots(rc):
            if self._cfs_dir(rc, root).is_dir():
                return True
        return False

    def _read_manifest(self, path):
        '''Parse a `.cfs/manifest.hu` -> {specname: {src, dst, exclude:[...]}}. {} if absent/blank.'''
        from ..troveio import load
        if not Path(path).exists() or not Path(path).read_text(encoding='utf-8-sig').strip():
            return {}
        trove = load(path)
        specs = trove.root['specs'] if trove.root is not None else None
        out = {}
        if specs is not None:
            for i in range(specs.num_children):
                node = specs[i]
                ex = []
                exn = node['exclude'] if node is not None else None
                if exn is not None:
                    ex = [exn[j].value for j in range(exn.num_children)]
                out[node.key] = {'src': (node['src'].value if node['src'] is not None else node.key),
                                 'dst': (node['dst'].value if node['dst'] is not None else ''),
                                 'exclude': ex}
        return out

    def _write_manifest(self, rc, specs_map):
        '''Write the manifest into this component's `.cfs` dir in the CAPTURE root.'''
        self._write_manifest_at(self._cfs_dir(rc), specs_map)

    def _write_manifest_at(self, cfs, specs_map):
        '''Write `<cfs>/manifest.hu` from {specname: {src,dst,exclude}} and a `.gitignore` from the
        union of excludes (so a secret that lands via edit-through is never committed/synced).'''
        from ..troveio import emit_hu
        cfs = Path(cfs)
        cfs.mkdir(parents=True, exist_ok=True)
        (cfs / MANIFEST_NAME).write_text(emit_hu({'specs': specs_map}))
        excludes = sorted({g for s in specs_map.values() for g in s.get('exclude', [])})
        gi = cfs / '.gitignore'
        if excludes:
            gi.write_text('# generated by configsys from manifest.hu exclude: — secrets never sync\n'
                          + '\n'.join(excludes) + '\n')
        elif gi.exists():
            gi.unlink()

    def _config_specs(self, rc):
        '''Config specs (kind=config), EXCLUDING legacy shell-glue snippets declared the old way with
        an inline src/dst under bash.d/ or shell/ — those read as config but belong to the shell
        layout, so they never get a .cfs marker/manifest entry or a capture.'''
        return [(n, src, dst, ab) for n, src, dst, ab, kind in self._specs(rc)
                if kind == 'config' and not (src.startswith('bash.d/') or src.startswith('shell/'))]

    def _ensure_marker(self, rc):
        '''Create/refresh the `.cfs` marker + manifest for a component's config specs (the #5
        managed signal — happens on install even with no content). Preserves any exclude: the user
        edited; never overwrites content. No-op for a glue-only component.'''
        cfg = self._config_specs(rc)
        if not cfg:
            return
        existing = self._read_manifest(self._cfs_dir(rc) / MANIFEST_NAME)
        specs_map = {}
        for name, src, dst, _ab in cfg:
            prev = existing.get(name, {})
            specs_map[name] = {'src': src, 'dst': dst, 'exclude': prev.get('exclude', [])}
        self._write_manifest(rc, specs_map)

    def _excludes_for(self, rc, name):
        '''The exclude globs recorded for a spec (from the manifest), [] if none.'''
        man = self._read_manifest(self._cfs_dir(rc) / MANIFEST_NAME)
        return man.get(name, {}).get('exclude', [])

    def _is_excluded(self, rel, globs):
        '''True if a relative path (POSIX) matches any exclude glob — matched against the full path
        AND its basename, so `.env`/`id_*` hit at any depth and `secrets/` hits the dir.'''
        rel = rel.replace(os.sep, '/').strip('/')
        base = rel.rsplit('/', 1)[-1]
        for g in globs:
            gg = g.rstrip('/')
            if fnmatch.fnmatch(rel, gg) or fnmatch.fnmatch(base, gg) or rel == gg or base == gg:
                return True
            if fnmatch.fnmatch(rel, gg + '/*'):            # anything under an excluded dir
                return True
        return False

    def _store_path(self, src):
        '''Where a SHIPPED TEMPLATE materializes: the machine-local store, at the same relative
        `src` (bash.d/btop.sh -> ~/.config/configsys/dotfiles/bash.d/btop.sh). None if no store.
        Pure — no side effects (used both to decide the link target and, after copy, to link it).'''
        store = getattr(self.paths, 'user_dotfiles_dir', None) if self.paths is not None else None
        return (Path(store) / src) if store is not None else None

    def _link_source(self, srcpath, tier, src):
        '''The path a link should point AT. For a shipped template (tier 'template', content living in
        the repo/defining layer) that's the machine-local STORE copy — so a link NEVER references the
        repo (requirement #4). For user content (tier 'user') or unpopulated (None), it's srcpath as
        resolved. Pure; `_materialize` does the actual copy before we link.'''
        if tier == 'template':
            dest = self._store_path(src)
            if dest is not None:
                return dest
        return srcpath

    def _materialize(self, srcpath, src):
        '''Copy a shipped template into the machine-local store (idempotent — only when the store
        lacks it), so the subsequent link points at a user-owned file instead of the repo. Returns
        the store path (or srcpath if there's no store / nothing to copy).'''
        return self._materialize_to(srcpath, self._store_path(src))

    def _materialize_to(self, srcpath, dest, executable=False):
        '''Copy `srcpath` to `dest` (idempotent — only when `dest` is absent); with `executable`, set
        a+x on the result (glue snippets: the loader sources only executable files). Returns dest
        (or srcpath if there's nothing to copy / no dest).'''
        if dest is None or not srcpath.exists():
            return srcpath
        # The store must hold a REAL, user-owned file — a symlink at `dest` is never valid here. It
        # also breaks the `dest.exists()` check: a LOOPING/broken link makes exists() falsely report
        # "absent" (its stat raises), so copy2 would then open THROUGH the loop -> ELOOP crash. Clear
        # any symlink (is_symlink() lstats, so it sees a looping link) before copying real content.
        if dest.is_symlink():
            dest.unlink()
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            if srcpath.is_dir():
                shutil.copytree(srcpath, dest)
            else:
                shutil.copy2(srcpath, dest)
        if executable and dest.is_file():
            os.chmod(dest, os.stat(dest).st_mode | 0o111)
        return dest

    def _glue_store(self, dst):
        '''The machine-local store MIRROR of a glue dst: ~/.config/<shell>/conf.d/<x> maps to
        <store>/<shell>/conf.d/<x>, so the store lines up with the deployed layout (and links are
        uniform, never the repo — #4). None if there's no store or the dst isn't under ~/.config.'''
        store = getattr(self.paths, 'user_dotfiles_dir', None) if self.paths is not None else None
        if store is None:
            return None
        try:
            rel = self._expand(dst).relative_to(self._home() / '.config')
        except ValueError:
            return None
        return Path(store) / rel

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

    # -- per-shell loader hookup (loader: <shell>) ------------------------

    def _confd(self, shell):
        return self._expand(_SHELL_CONFD[shell])

    def _ensure_confd(self, shell):
        '''Ensure ~/.config/<shell>/conf.d/ exists (so fish/nu auto-source find it, and links have a
        home). Returns the dir.'''
        d = self._confd(shell)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _rc_block(self, shell):
        confd = self._confd(shell)
        body = _RC_SOURCE[shell].format(confd=shlex.quote(str(confd)))
        return f'{_RC_BEGIN}\n{body}\n{_RC_END}\n'

    def _rc_has_block(self, rc_path):
        try:
            return _RC_BEGIN in Path(rc_path).read_text()
        except (FileNotFoundError, OSError):
            return False

    def _ensure_shell_loader(self, shell):
        '''Idempotent hookup for a shell's conf.d loader. Always ensures the dir; for a shell that
        needs an rc line (zsh) inserts/refreshes ONE configsys-owned marker block in its rc file.
        fish (native conf.d auto-source), nu (punted) and bash (rides ~/.bash_aliases) get the dir
        only — no rc edit. Returns True if a hookup is now in place for this shell.'''
        self._ensure_confd(shell)
        rc_rel = _SHELL_RC.get(shell)
        if rc_rel is None:                                 # fish / nu / bash: dir is the whole job
            return True
        rc_path = self._expand(rc_rel)
        if rc_path.is_symlink():                           # a captured/managed rc — its own content
            return False                                   # owns the source line; never edit-through
        block = self._rc_block(shell)
        existing = ''
        if rc_path.exists():
            existing = rc_path.read_text()
        if _RC_BEGIN in existing:                          # replace our block in place (idempotent)
            new = re.sub(re.escape(_RC_BEGIN) + r'.*?' + re.escape(_RC_END) + r'\n?',
                         block, existing, flags=re.DOTALL)
        else:
            sep = '' if (not existing or existing.endswith('\n')) else '\n'
            new = f'{existing}{sep}{block}'
        rc_path.parent.mkdir(parents=True, exist_ok=True)
        rc_path.write_text(new)
        return True

    def _remove_shell_loader(self, shell):
        '''Remove our rc block for a shell (leaves the conf.d dir + any content alone).'''
        rc_rel = _SHELL_RC.get(shell)
        if rc_rel is None:
            return
        rc_path = self._expand(rc_rel)
        if not rc_path.exists():
            return
        text = rc_path.read_text()
        if _RC_BEGIN not in text:
            return
        new = re.sub(r'\n?' + re.escape(_RC_BEGIN) + r'.*?' + re.escape(_RC_END) + r'\n?',
                     '\n', text, flags=re.DOTALL)
        rc_path.write_text(new)

    def _loader_shell(self, rc):
        '''The shell a `loader: <shell>` component hooks up, or None.'''
        return rc.fields.get('loader')

    def _pairs(self, rc):
        '''[(source_path, target_path, absorb_path_or_None)] resolved for this machine — `src`
        resolved through the content search-path (_resolve), kind-aware.'''
        return [(self._resolve(src, rc, kind)[0], self._expand(dst),
                 self._expand(absorb) if absorb else None)
                for _n, src, dst, absorb, kind in self._specs(rc)]

    def spec_states(self, rc):
        '''[(name, target_display, state, src_root, src_rel, here, kind)] for `dotfiles status`.
        `kind` is 'config' (content you own) or 'glue' (a shipped shell-integration snippet) — the
        two belong to different state machines (see the TUI legend).
        state is one of:
          linked    — our symlink is in place (managed & active)
          adopted   — your content exists in a user root; not linked yet (capture done)
          managed   — config `.cfs` marker exists but no content captured yet (managed-when-empty,
                      #5 — the component is installed; if a real on-system file sits at dst it's kept
                      and startup warns you to capture it)
          unmanaged — a real on-system file with NO marker and NO adopted content -> AT RISK on install
          template  — a shipped template exists, not adopted, nothing on-system yet
          empty     — declared, no content/marker anywhere, nothing on-system (a personal dotfile
                      you haven't captured; harmless — install is a no-op until you do).
        (src_root, src_rel) locate the managed content: for content that EXISTS (linked/adopted/
        template) the root it lives in (a user store, or the base <repo> for a template); for
        managed/unmanaged/empty the capture destination (where it WILL land). `here` is True in the
        former case, False when it's prospective. The caller labels the distinct roots.'''
        capture_root = self._capture_root()
        marker = self._marker_present(rc)
        out = []
        for name, src, dst, _absorb, kind in self._specs(rc):
            srcpath, tier, root = self._resolve(src, rc, kind)
            tgt = self._expand(dst)
            if srcpath.exists() and os.path.realpath(str(tgt)) == os.path.realpath(str(srcpath)):
                state = 'linked'                          # our link, or a store copy reached via a
                                                          # dir-symlinked conf.d (realpath identity)
            elif tgt.is_symlink() or tgt.exists():        # a real file/dir, or a foreign symlink
                state = ('adopted' if tier == 'user'
                         else 'managed' if kind == 'config' and marker else 'unmanaged')
            elif tier == 'user':
                state = 'adopted'                         # captured, dst absent -> links cleanly
            elif tier == 'template':
                state = 'template'
            elif kind == 'config' and marker:
                state = 'managed'                         # #5: marked, content not captured yet
            else:
                state = 'empty'
            if state in ('linked', 'adopted', 'template'):
                src_root, here = root, True               # content exists here -> show its real path
                try:
                    rel = str(srcpath.relative_to(src_root))
                except ValueError:
                    rel = src
            else:                                         # managed/unmanaged/empty -> capture dest
                src_root, here = capture_root, False      # a config lands under <comp>.cfs/<src>
                rel = f'{rc.comp}{CFS_SUFFIX}/{src}' if kind == 'config' else src
            out.append((name, self.display_path(tgt), state, src_root, rel, here, kind))
        return out

    def capture_plan(self, rc, force=False):
        '''What `dotfiles capture` WOULD do for this component — pure, no side effects. CONFIG specs
        only (glue is shipped, never captured). Per spec, (name, dst_path, dest_path, action):
          copy         — dst is a real file/dir; copy it into the `<comp>.cfs/` store
          skip-linked  — dst is already our managed symlink (nothing to adopt)
          skip-absent  — dst doesn't exist (or a broken symlink) — nothing to adopt
          skip-exists  — the store already holds content for this src (pass force to overwrite)
        dest is `<capture_root>/<comp>.cfs/<src>`.'''
        cfs = self._cfs_dir(rc)
        out = []
        for name, src, dst, _absorb in self._config_specs(rc):
            tgt = self._expand(dst)
            dest = cfs / src
            srcpath, _tier, _root = self._resolve(src, rc, 'config')
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

    def _suggest_secrets(self, dst):
        '''Scan a to-be-captured dir for secret-shaped entries (top level + one deep) and return the
        matching exclude globs — pre-filled into a fresh manifest so credentials never enter the
        store. Cheap and best-effort; the user trims the list.'''
        found = set()
        if not dst.is_dir():
            return []
        try:
            entries = list(dst.rglob('*'))
        except OSError:
            entries = []
        for e in entries:
            try:
                rel = e.relative_to(dst).as_posix()
            except ValueError:
                continue
            for g in _SECRET_GLOBS:
                if self._is_excluded(rel, [g]):
                    found.add(g)
        return sorted(found)

    def capture(self, rc, force=False):
        '''Adopt on-system config for `rc` into the `<comp>.cfs/` store — the WRITE half of
        capture_plan. Copies each `copy` target FROM the on-system dst INTO the store, SKIPPING any
        path the manifest excludes (secrets), and writes/refreshes the manifest (auto-suggesting
        secret-shaped excludes on FIRST capture) + `.gitignore`. Never modifies or deletes an
        on-system file. Returns the list of (name, dst, dest) captured.'''
        man = self._read_manifest(self._cfs_dir(rc) / MANIFEST_NAME)
        first = not man                                    # no manifest yet -> first capture here
        done = []
        specs_map = {}
        for name, src, dst, _absorb in self._config_specs(rc):
            excludes = list(man.get(name, {}).get('exclude', []))
            if first:                                      # auto-suggest secrets into the new manifest
                excludes = sorted(set(excludes) | set(self._suggest_secrets(self._expand(dst))))
            specs_map[name] = {'src': src, 'dst': dst, 'exclude': excludes}
        # capture_plan is computed against pre-copy state; snapshot its actions first.
        plan = {name: action for name, _dst, _dest, action in self.capture_plan(rc, force)}
        for name, src, dst, _absorb in self._config_specs(rc):
            if plan.get(name) != 'copy':
                continue
            tgt = self._expand(dst)
            dest = self._cfs_dir(rc) / src
            excludes = specs_map[name]['exclude']
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.is_symlink() or dest.is_file():
                dest.unlink()
            elif dest.is_dir():
                shutil.rmtree(dest)
            if tgt.is_dir():
                def _ignore(dirpath, names, _tgt=tgt, _ex=excludes):
                    rel_base = os.path.relpath(dirpath, str(_tgt))
                    skip = []
                    for n in names:
                        rel = n if rel_base == '.' else f'{rel_base}/{n}'
                        if self._is_excluded(rel, _ex):
                            skip.append(n)
                    return set(skip)
                shutil.copytree(tgt, dest, ignore=_ignore)
            elif not self._is_excluded(src, excludes):
                shutil.copy2(tgt, dest)
            done.append((name, tgt, dest))
        # Always (re)write the marker/manifest so management is recorded even if nothing copied.
        if specs_map:
            self._write_manifest(rc, specs_map)
        return done

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        '''"linked" when every spec's dst is our symlink to present content; else "managed" when a
        config `.cfs` marker exists (managed-when-empty, #5 — the component IS installed, content just
        isn't captured/linked yet); else None (not installed).'''
        loader = self._loader_shell(rc)
        if loader:
            if not self._confd(loader).is_dir():
                return None
            rc_rel = _SHELL_RC.get(loader)
            if rc_rel is not None and not self._rc_has_block(self._expand(rc_rel)):
                return None
            return 'linked'
        specs = self._specs(rc)
        if not specs:
            return None
        all_linked = True
        for _name, src, _dst, absorb, kind in specs:
            srcpath, _tier, _root = self._resolve(src, rc, kind)
            tgt = self._expand(_dst)
            # "linked" = the deploy target RESOLVES to the managed store copy. That holds for our
            # per-file symlink AND when ~/.config/<shell>/conf.d is itself a dir-symlink to the store
            # (the target is then a real file that IS the store copy) — realpath identity covers both;
            # requiring tgt.is_symlink() would wrongly report the dir-link case as uninstalled.
            if not (srcpath.exists()
                    and os.path.realpath(str(tgt)) == os.path.realpath(str(srcpath))):
                all_linked = False
                break
        if all_linked:
            return 'linked'
        if self._marker_present(rc):
            return 'managed'
        return None

    def warnings(self, rc):
        '''[(tag, text)] warn-only startup checks (design #2/#5/#4), never mutate:
          * capture   — a config `.cfs` marked-managed whose dst holds a real, un-captured file
                        (you have config configsys should adopt before it can manage it);
          * invariant — a managed link that STILL points into the repo (#4 breach; re-link to fix).
        Cheap and side-effect-free — safe to run on every load.'''
        out = []
        repo = os.path.realpath(self.paths.dotfiles_dir) if self.paths is not None else None
        managed = None                                     # computed lazily (one marker probe/comp)
        for _name, src, dst, _absorb, kind in self._specs(rc):
            srcpath, _tier, _root = self._resolve(src, rc, kind)
            tgt = self._expand(dst)
            if tgt.is_symlink() and repo is not None:
                raw = os.readlink(tgt)
                rp = (os.path.realpath(tgt) if tgt.exists() else
                      (raw if os.path.isabs(raw)
                       else os.path.normpath(os.path.join(os.path.dirname(str(tgt)), raw))))
                if rp == repo or rp.startswith(repo + os.sep):
                    out.append(('dotfiles', f'{rc.comp}: {self.display_path(tgt)} still links into '
                                f'the repo — unlink and re-link it to point it at your store'))
            elif kind == 'config' and not srcpath.exists() and tgt.exists():
                if managed is None:
                    managed = self._marker_present(rc)
                if managed:
                    out.append(('dotfiles', f'{rc.comp}: config at {self.display_path(tgt)} is managed '
                                f'but not captured — `configsys dotfiles capture {rc.comp}`'))
        return out

    def get_latest(self, rc):
        return None  # dotfiles track the repo; no version notion

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def _force(self):
        return bool(getattr(self.paths, 'dotfiles_force', False)) if self.paths is not None else False

    def install(self, rc):
        loader = self._loader_shell(rc)
        if loader:                                         # a per-shell loader component (loader: zsh)
            self._ensure_shell_loader(loader)
            return Result(f'dotfiles: {loader} conf.d loader hooked up', 0)
        specs = self._specs(rc)
        if not specs:
            return Result.fail(f'{rc.comp}: dotfiles binding has no link specs (needs src:/dst:)')
        force = self._force()
        # #5: stamp the config `.cfs` marker + manifest so this location is "managed" even before any
        # content is captured/linked. No-op for a glue-only component. Runs even if we refuse below —
        # refusing is itself an act of management (we won't clobber what we now track).
        self._ensure_marker(rc)
        pairs, blocked = [], []
        for _name, src, dst, absorb, kind in specs:
            srcpath, tier, _root = self._resolve(src, rc, kind)
            # GLUE deploys to the machine-local store MIRROR (<store>/<shell>/conf.d/), executable, so
            # the loader sources it and the store lines up with the deployed dir. A config TEMPLATE
            # links to its store copy. Either way a link never references the repo (#4).
            link_src = self._glue_store(dst) if kind == 'glue' else self._link_source(srcpath, tier, src)
            if link_src is None:
                link_src = srcpath
            tgt = self._expand(dst)
            ab = self._expand(absorb) if absorb else None
            pairs.append((srcpath, tier, src, link_src, tgt, ab, kind))
            # REFUSE to replace a real on-system file/dir with a TEMPLATE the user hasn't adopted.
            # tier 'user' = you captured it -> linking to your own content (auto-backing up whatever
            # sits at dst) is the sanctioned path; tier None = unpopulated -> managed-when-empty, the
            # shell skips it and leaves any real file alone (startup warns to capture); an
            # `absorb-into` spec has its own relocation. So only an un-adopted TEMPLATE over a real dst
            # is blocked. A symlink WE made (store copy OR legacy repo template) is ours — safe to
            # re-point, not a clobber (so re-installing a stale repo link re-points it at the store).
            ours = tgt.is_symlink() and os.path.realpath(tgt) in (
                os.path.realpath(link_src), os.path.realpath(srcpath))
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
        # Deploy content into the machine-local store NOW (only the specs we'll link), so the link
        # below points at a user-owned copy and never into the repo. Glue goes to the store's
        # <shell>/conf.d/ mirror and is made executable (idempotently, so an already-materialized
        # copy still gets its +x bit); a config template lands at its store path.
        for _srcpath, tier, src, link_src, _tgt, _ab, kind in pairs:
            if kind == 'glue':
                self._materialize_to(_srcpath, link_src, executable=True)
            elif tier == 'template':
                self._materialize(_srcpath, src)
        lines = ['set -e']
        for _srcpath, _tier, src, link_src, tgt, absorb, _kind in pairs:
            # If the deploy target already RESOLVES to the store copy — e.g. ~/.config/<shell>/conf.d
            # is itself a symlink to the store dir — then the store file IS the deployed file, and
            # `ln -sfn store/x  conf.d/x` would resolve through the dir-link to `ln store/x store/x`,
            # a symlink pointing at ITSELF (ELOOP). Skip the link/backup: materialize already placed
            # the content, and the dir-link deploys it.
            try:
                if link_src != tgt and os.path.realpath(str(link_src)) == os.path.realpath(str(tgt)):
                    continue
            except OSError:
                pass
            s, t = shlex.quote(str(link_src)), shlex.quote(str(tgt))
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
        loader = self._loader_shell(rc)
        if loader:
            self._remove_shell_loader(loader)              # drop the rc block; leave conf.d + content
            return Result(f'dotfiles: {loader} conf.d loader removed', 0)
        pairs = self._pairs(rc)
        if not pairs:
            return Result.fail(f'{rc.comp}: dotfiles binding has no link specs (needs src:/dst:)')
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
        loader = self._loader_shell(rc)
        if loader:
            return self.display_path(self._confd(loader))
        targets = [self.display_path(tgt) for _src, tgt, _absorb in self._pairs(rc)]
        return '; '.join(targets) if targets else None

    def lock(self, rc):
        return Result('(dotfiles lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(dotfiles unlock recorded in ledger)', 0)
