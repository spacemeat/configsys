'''glue.py — the glue driver: shell-integration enablement (`via: glue`).

Glue is the shell wiring a component needs to be USABLE — PATH, aliases, env, completions,
shell init — deployed as small snippets under the uniform `~/.config/<shell>/conf.d/` dir, plus
the per-shell LOADERS that make each shell source that dir. It is the sibling of the dotfiles
driver (`via: dotfiles`), which manages a component's own reposited CONFIG. The two were one driver
historically; they are split so each is its own concern (and, later, its own TUI page).

A `via: glue` binding is one of:
  * `glue: <name>`   — a snippet: link `shell/<shell>/<name>.<ext>` (a `bash.d/<name>.sh` fallback
                       for the pre-move layout) into `~/.config/<shell>/conf.d/<name>.<ext>`, for
                       each INSTALLED shell that ships a variant. Snippets deploy through the
                       machine-local store MIRROR (never linking the repo).
  * `loader: <shell>`— hook one shell up to source its conf.d (zsh needs an rc marker-block; fish
                       auto-sources natively; bash rides `~/.bash_aliases`; elvish/nushell inline the
                       snippets into the rc — they can't dynamically source a dir).

User-space only (no sudo); no version — glue is "active" or not.

Storage is SEGREGATED from the dotfiles driver: glue authoring lives at `glue/shell/<shell>/
<name>.<ext>` (repo/plugin), materializes into the machine-local glue store `<state>/glue/<shell>/
conf.d/<name>.<ext>`, and links into `~/.config/<shell>/conf.d/`. The dotfiles driver's `dotfiles/`
tree (config `*.cfs/` captures) and this `glue/` tree never share a directory.
'''

import os
import re
import shlex
import shutil
from pathlib import Path

from ..driver import Driver
from ..runner import Result

_VAR = re.compile(r'\$[A-Za-z_][A-Za-z0-9_]*')
BACKUP_SUFFIX = '.pre-configsys'
# bash has no native conf.d — it rides the distro `~/.bash_aliases` convention: shell-glue links
# ~/.bash_aliases to the shipped `bash_aliases` loader file (which sources conf.d/*.sh), absorbing
# any pre-existing real ~/.bash_aliases into conf.d so the user's own aliases keep running.
_BASH_ALIASES_SRC = 'bash_aliases'
_BASH_ABSORB = '~/.config/bash/conf.d/pre-configsys-aliases.sh'

# snippets, keyed by shell. `_SHELL_EXT` = the file extension per shell; `_SHELL_CONFD` = the active
# loader dir (uniform ~/.config/<shell>/conf.d/, mirroring fish's native one). Repo ships bash
# variants today; other shells activate the moment their variant exists.
_SHELL_EXT = {'bash': 'sh', 'zsh': 'zsh', 'fish': 'fish', 'nu': 'nu', 'elvish': 'elv'}
_SHELL_CONFD = {'bash': '~/.config/bash/conf.d', 'zsh': '~/.config/zsh/conf.d',
                'fish': '~/.config/fish/conf.d', 'nu': '~/.config/nushell/conf.d',
                'elvish': '~/.config/elvish/conf.d'}
_GLUE_SHELLS = ('bash', 'zsh', 'fish', 'nu', 'elvish')
# the component that INSTALLS each shell (for the managed-install detection) — identity except nu.
_SHELL_COMPONENT = {'nu': 'nushell'}

# loaders (`loader: <shell>`): hook a shell up to run its ~/.config/<shell>/conf.d/* snippets.
# fish auto-sources conf.d natively (no rc edit); bash rides the distro ~/.bash_aliases convention;
# zsh needs one configsys-owned, marker-delimited rc block that SOURCES the dir; elvish and nushell
# are INLINE (see below). The markers make the block idempotent + cleanly removable.
_RC_BEGIN = '# >>> configsys glue >>>'
_RC_END = '# <<< configsys glue <<<'
_SHELL_RC = {'zsh': '~/.zshrc', 'elvish': '~/.config/elvish/rc.elv',
             'nu': '~/.config/nushell/config.nu'}

# GESTALT (inline) shells: neither elvish nor nushell can dynamically source a dir of snippets into
# the interactive scope. Elvish's per-file `eval` ISOLATES namespaces (a sourced file's `fn`/`var`
# defs never reach the interactive shell). Nushell parses the WHOLE program before running, so
# `source` is a parse-time keyword whose path must be a compile-time constant — you can't loop-source
# conf.d at all. For both, the rc marker block INLINES the concatenated conf.d snippet contents
# directly (so definitions land in the interactive scope), regenerated on every (de)activation. It's
# also faster — one block, not N sourced files. (Consequence: an inline-rc shell's rc is glue-owned
# and cannot be a dotfiles capture — capturing freezes the block — so these shells have no -dotfiles.)
_INLINE_SHELLS = ('elvish', 'nu')

# A `#!cs-eval <cmd>` line makes a snippet a GENERATOR: the inline loader runs <cmd> at (de)activation
# and inlines its stdout (an init-eval tool's shell code) instead of the snippet text — the bridge for
# tools like zoxide/atuin on nushell, which has no runtime source/eval. Self-guards: a failing command
# inlines nothing.
_EVAL_DIRECTIVE = re.compile(r'^#!\s*cs-eval\s+(.+?)\s*$')

# GLUE speaks a binary vocabulary (active/available/inactive) — a ship->activate toggle. This maps
# the underlying spec/loader states to those labels (identity for anything unlisted). Shared by the
# TUI and the CLI status so they never diverge.
GLUE_STATE_LABEL = {'linked': 'active', 'loader-on': 'active', 'drifted': 'changed',
                    'template': 'available', 'loader-off': 'inactive'}
# how each rc-driven shell sources its conf.d dir (empty-glob-safe).
_RC_SOURCE = {
    'zsh': ('setopt local_options null_glob\n'
            'for _f in {confd}/*.zsh; do source "$_f"; done\n'
            'unset _f'),
    # Elvish: [nomatch-ok] (attached to the * wildcard) so an empty conf.d doesn't error; the list
    # brackets make the glob a single iterable; `eval (slurp < $f)` sources each file.
}


class Glue(Driver):
    name = 'glue'
    privileged = False
    default_scope = 'user'

    # -- specs & paths ----------------------------------------------------

    def _specs(self, rc):
        '''[(name, src, dst)] snippet specs for this component — the `glue: <name>` field (top-level
        or nested under a sub-map), one spec per installed shell that ships a variant. A `loader:`
        component has NO snippet specs (it is a pure rc hookup, handled directly by install).'''
        f = rc.fields
        out = []
        if f.get('glue'):
            out.extend(self._glue_specs(f['glue'], rc))
        for _key, val in f.items():
            if isinstance(val, dict) and 'glue' in val:      # nested glue (a mixed component's glue half)
                out.extend(self._glue_specs(val['glue'], rc))
        return out

    def _glue_specs(self, glue, rc):
        '''snippet specs for a glue name: one per shell that actually ships a snippet.'''
        return [(f'{glue}@{shell}', src, f'{_SHELL_CONFD[shell]}/{glue}.{ext}')
                for shell, ext, src in self._glue_variants(glue, rc)]

    def _installed_shells(self):
        '''Which shells to ACTIVATE glue for: those whose binary is on PATH (design: per INSTALLED
        shell, NOT $SHELL — $SHELL is only the login shell) OR that configsys MANAGES (its binary sits
        in the managed install dir). The managed check cracks the tarball chicken-and-egg: a shell you
        just installed through configsys (e.g. nushell to ~/apps) shows in the Glue TUI immediately,
        without opening a fresh shell to get it on PATH first. Overridable via CONFIGSYS_GLUE_SHELLS
        (comma-separated) for tests / to force a set. Bash is the baseline if nothing is detected.'''
        env = self._env()
        forced = env.get('CONFIGSYS_GLUE_SHELLS')
        if forced is not None:
            return [s.strip() for s in forced.split(',') if s.strip()]
        on_path = {s for s in _GLUE_SHELLS if shutil.which(s, path=env.get('PATH'))}
        managed = self._managed_shells()
        found = [s for s in _GLUE_SHELLS if s in on_path or s in managed]   # _GLUE_SHELLS order, deduped
        return found or ['bash']

    def _managed_shells(self):
        '''Glue shells configsys manages: the shell's binary is present in its managed install dir (read
        from the glue-locations cache — component -> dir). Lets a tarball shell be glue-managed before a
        fresh shell puts it on PATH. Empty when the cache is cold (falls back to PATH detection).'''
        locs = self._read_location_cache()
        out = []
        for shell in _GLUE_SHELLS:
            d = locs.get(_SHELL_COMPONENT.get(shell, shell))
            if d and self._shell_binary_in(shell, self._expand(d)):
                out.append(shell)
        return out

    def _read_location_cache(self):
        '''{component: dir} from the glue-locations.tsv cache (what configsys writes for the shell glue).
        Empty (best-effort) when absent/unreadable.'''
        out = {}
        f = getattr(self.paths, 'glue_locations_file', None) if self.paths is not None else None
        if f is None:
            return out
        try:
            for line in Path(f).read_text(encoding='utf-8').splitlines():
                name, sep, path = line.partition('\t')
                if sep and name and path:
                    out[name] = path
        except OSError:
            pass
        return out

    @staticmethod
    def _shell_binary_in(shell, d):
        '''True if an executable named `shell` lives directly in `d`, a versioned subdir, or a bin/ under
        it (covers a flat tarball like elvish and a versioned one like nushell's nu-*/nu).'''
        if not d.is_dir():
            return False
        for pat in (shell, f'*/{shell}', f'bin/{shell}', f'*/bin/{shell}'):
            for m in d.glob(pat):
                if m.is_file() and os.access(m, os.X_OK):
                    return True
        return False

    def _glue_variants(self, glue, rc):
        '''(shell, ext, src) for each INSTALLED shell that has a snippet for this glue name. The
        SOURCE is the AUTHORITATIVE shipped copy — the highest content root (your plugin > the repo
        template) carrying the `shell/<shell>/<name>.<ext>` (or legacy `bash.d/<name>.sh`) authoring
        layout — NOT the machine-local store DEPLOY mirror (`<shell>/conf.d/`). That's deliberate:
        the store is a cache, so resolving to the authoritative source lets install re-materialize
        over a STALE cached copy when the repo/plugin snippet has changed. Only when no authoritative
        source exists anywhere (its source was removed) do we fall back to an already-deployed store
        mirror, so the snippet still reads as active instead of vanishing.'''
        out = []
        installed = self._installed_shells()
        for shell in _GLUE_SHELLS:
            if shell not in installed:                     # activate only where the shell is present
                continue
            ext = _SHELL_EXT[shell]
            auth = [f'shell/{shell}/{glue}.{ext}']         # repo/plugin authoring layout (authoritative)
            if shell == 'bash':
                auth.append(f'bash.d/{glue}.sh')           # legacy authoring layout (authoritative)
            chosen = None
            for root, _tier in self._content_roots(rc):    # store, primary plugin, then repo template
                for src in auth:
                    if (root / src).exists():
                        chosen = src
                        break
                if chosen:
                    break
            if chosen is None:                             # fallback: an existing store deploy mirror
                mirror = f'{shell}/conf.d/{glue}.{ext}'
                for root, _tier in self._content_roots(rc):
                    if (root / mirror).exists():
                        chosen = mirror
                        break
            if chosen:
                out.append((shell, ext, chosen))
        return out

    def _home(self):
        return self.paths.home if self.paths is not None else Path.home()

    def _env(self):
        return self.paths.env if self.paths is not None else dict(os.environ)

    def _defining_root(self, rc):
        '''The `glue/` dir NEXT TO the .hu file that defined the component (`rc.source`) — a
        plugin / user layer ships glue alongside its definitions. Falls back to the base repo's
        glue dir when the component carries no source (a hand-built rc in tests).'''
        src_file = getattr(rc, 'source', '') or ''
        if src_file:
            return Path(src_file).parent / 'glue'
        return self.paths.glue_dir if self.paths is not None else Path('glue')

    def _content_roots(self, rc):
        '''Ordered (root, tier) content roots for resolving `src`, highest precedence first:
        the machine-local glue store, then the primary plugin's glue/, then the defining layer.'''
        roots = []
        p = self.paths
        if p is not None:
            for attr in ('user_glue_dir', 'primary_glue_dir'):
                d = getattr(p, attr, None)
                if d is not None:
                    roots.append((Path(d), 'user'))
        roots.append((self._defining_root(rc), 'template'))
        return roots

    def _resolve(self, src, rc):
        '''(resolved_src_path, tier, root) — the first content root that actually HAS `src` wins
        (a snippet `src` is already a root-relative path, e.g. `shell/bash/x.sh`). If none has it,
        the defining-layer path with tier None (declared but no content anywhere).'''
        for root, tier in self._content_roots(rc):
            cand = root / src
            if cand.exists():
                return cand, tier, root
        dr = self._defining_root(rc)
        return dr / src, None, dr

    def _store_path(self, src):
        '''Where a SHIPPED TEMPLATE materializes: the machine-local glue store, at the same relative src.'''
        store = getattr(self.paths, 'user_glue_dir', None) if self.paths is not None else None
        return (Path(store) / src) if store is not None else None

    def _materialize_to(self, srcpath, dest, executable=False, refresh=False):
        '''Copy `srcpath` to `dest` (idempotent — only when `dest` is absent, or `refresh` and the
        content differs; glue is SHIPPED content, so refreshing the store cache from an updated
        source is safe and desired). With `executable`, set a+x on the result (the loader sources
        only executable files). Returns dest (or srcpath if there's nothing to copy / no dest).'''
        if dest is None or not srcpath.exists():
            return srcpath
        if dest.is_symlink():                              # never leave a symlink in the store
            dest.unlink()
        need = not dest.exists()
        if not need and refresh and dest.is_file() and srcpath.is_file():
            try:
                need = dest.read_bytes() != srcpath.read_bytes()   # source changed -> re-cache it
            except OSError:
                need = True
        if need:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() or dest.is_symlink():
                if dest.is_dir() and not dest.is_symlink():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            if srcpath.is_dir():
                shutil.copytree(srcpath, dest)
            else:
                shutil.copy2(srcpath, dest)
        if executable and dest.is_file():
            os.chmod(dest, os.stat(dest).st_mode | 0o111)
        return dest

    def _glue_store(self, dst):
        '''The machine-local glue-store MIRROR of a snippet dst: ~/.config/<shell>/conf.d/<x> maps to
        <glue-store>/<shell>/conf.d/<x>, so the store lines up with the deployed layout (and links are
        uniform, never the repo). None if there's no store or the dst isn't under ~/.config.'''
        store = getattr(self.paths, 'user_glue_dir', None) if self.paths is not None else None
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

    # -- per-shell loader hookup (loader: <shell> | all) ------------------

    def _loader_shells(self, rc):
        '''The shells a `loader:` component hooks up: [<shell>] for a specific one, every INSTALLED
        shell for `loader: all` (the shell-glue substrate), or [] if not a loader component.'''
        loader = rc.fields.get('loader')
        if not loader:
            return []
        if loader == 'all':
            return self._installed_shells()
        return [loader]

    def _confd(self, shell):
        return self._expand(_SHELL_CONFD[shell])

    def _ensure_confd(self, shell):
        '''Ensure ~/.config/<shell>/conf.d/ exists (so fish auto-source finds it, the inline shells'
        snippets have a home to be read from, and links have a home). Returns the dir.'''
        d = self._confd(shell)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _rc_block(self, shell):
        if shell in _INLINE_SHELLS:
            return self._inline_block(shell)
        confd = self._confd(shell)
        body = _RC_SOURCE[shell].format(confd=shlex.quote(str(confd)))
        return f'{_RC_BEGIN}\n{body}\n{_RC_END}\n'

    def _inline_block(self, shell):
        '''The GESTALT rc block for an inline shell (elvish/nushell): the concatenated contents of its
        active conf.d snippets, wrapped in the markers — so definitions run in the interactive namespace
        (elvish's per-file `eval` would discard them; nushell can't source a dir at all). A SNAPSHOT of
        conf.d, regenerated whenever a snippet is (de)activated (install/uninstall call
        _ensure_shell_loader). conf.d entries are symlinks into the store; read_text follows them.
        A snippet carrying a `#!cs-eval <cmd>` directive is a GENERATOR: its command's stdout is inlined
        instead of its text (the init-eval bridge — see _eval_directive).'''
        ext = _SHELL_EXT[shell]
        confd = self._confd(shell)
        parts = []
        if confd.is_dir():
            for f in sorted(confd.iterdir()):              # 00- first -> substrate defines helpers early
                if not f.name.endswith(f'.{ext}'):
                    continue
                try:
                    content = f.read_text()
                except OSError:
                    continue
                cmd = self._eval_directive(content)
                if cmd is not None:                        # a generator snippet: inline the cmd's stdout
                    out = self._run_eval(cmd)
                    if out.strip():
                        parts.append(f'# >> {f.name} (generated: {cmd})\n{out.rstrip(chr(10))}')
                    # a tool that's absent / too old to emit a nu init -> nothing inlined (self-guard)
                else:
                    parts.append(f'# >> {f.name}\n{content.rstrip(chr(10))}')
        body = '\n\n'.join(parts)
        return f'{_RC_BEGIN}\n{body}\n{_RC_END}\n'

    def _eval_directive(self, content):
        '''The `<cmd>` of a `#!cs-eval <cmd>` line anywhere in a snippet (a GENERATOR snippet), else
        None. Used for init-eval tools (zoxide/atuin) on a shell with no runtime `source`/eval: the
        driver runs the command at (de)activation and inlines its stdout into the gestalt block.'''
        for line in content.splitlines():
            m = _EVAL_DIRECTIVE.match(line.strip())
            if m:
                return m.group(1).strip()
        return None

    def _run_eval(self, cmd):
        '''Run a generator snippet's command, returning its stdout ('' on ANY failure — a tool that's
        absent or too old to emit a nu/elvish init must never break the block).'''
        try:
            r = self.runner.run(cmd, capture=True)
        except Exception:                                  # noqa: BLE001 — a flaky init must not brick glue
            return ''
        return (r.stdout or '') if (r is not None and r.ok) else ''

    def _rc_has_block(self, rc_path):
        try:
            return _RC_BEGIN in Path(rc_path).read_text()
        except (FileNotFoundError, OSError):
            return False

    def _ensure_shell_loader(self, shell, rc=None):
        '''Idempotent hookup for a shell's conf.d loader. Always ensures the dir; bash also gets its
        ~/.bash_aliases link (see _link_bash_aliases); zsh inserts/refreshes ONE configsys-owned
        marker block that SOURCES the dir; elvish and nushell (gestalt/inline shells) insert/refresh a
        marker block that INLINES the concatenated conf.d snippets (_inline_block); fish (native
        auto-source) gets the dir only. Returns True if a hookup is in place for this shell.'''
        self._ensure_confd(shell)
        if shell == 'bash':                                # bash rides ~/.bash_aliases
            self._link_bash_aliases(rc)
            return True
        rc_rel = _SHELL_RC.get(shell)
        if rc_rel is None:                                 # fish / nu: dir is the whole job
            return True
        rc_path = self._expand(rc_rel)
        if rc_path.is_symlink():                            # a captured/managed rc owns its source line
            return False
        block = self._rc_block(shell)
        existing = rc_path.read_text() if rc_path.exists() else ''
        if _RC_BEGIN in existing:                           # replace our block in place (idempotent)
            new = re.sub(re.escape(_RC_BEGIN) + r'.*?' + re.escape(_RC_END) + r'\n?',
                         block, existing, flags=re.DOTALL)
        else:
            sep = '' if (not existing or existing.endswith('\n')) else '\n'
            new = f'{existing}{sep}{block}'
        rc_path.parent.mkdir(parents=True, exist_ok=True)
        rc_path.write_text(new)
        return True

    def _link_bash_aliases(self, rc):
        '''Link ~/.bash_aliases to the shipped `bash_aliases` loader (materialized into the store, so
        the link never points at the repo), absorbing any pre-existing real ~/.bash_aliases into
        conf.d/pre-configsys-aliases.sh (made a+x so the loader keeps sourcing it); a plain
        `.pre-configsys` backup if that absorb target is already taken. No-op if no bash_aliases is
        shipped in any content root (nothing to link).'''
        if rc is None:
            return
        srcpath, _tier, _root = self._resolve(_BASH_ALIASES_SRC, rc)
        if not srcpath.exists():
            return
        store = self._store_path(_BASH_ALIASES_SRC)
        link_src = self._materialize_to(srcpath, store) if store is not None else srcpath
        dst = self._home() / '.bash_aliases'
        if dst.is_symlink():                               # our (or a foreign) link -> replace
            dst.unlink()
        elif dst.exists():                                 # a real file -> absorb it, don't zap
            absorb = self._expand(_BASH_ABSORB)
            if absorb.exists():
                dst.rename(dst.with_name(dst.name + BACKUP_SUFFIX))
            else:
                absorb.parent.mkdir(parents=True, exist_ok=True)
                dst.rename(absorb)
                os.chmod(absorb, os.stat(absorb).st_mode | 0o111)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.symlink_to(link_src)

    def _remove_bash_aliases(self):
        '''Remove our ~/.bash_aliases symlink and restore what we displaced (the absorbed file, else
        a `.pre-configsys` backup). Leaves the conf.d dir + snippet content alone.'''
        dst = self._home() / '.bash_aliases'
        if dst.is_symlink():
            dst.unlink()
        absorb = self._expand(_BASH_ABSORB)
        backup = dst.with_name(dst.name + BACKUP_SUFFIX)
        if absorb.exists():
            absorb.rename(dst)
        elif backup.exists():
            backup.rename(dst)

    def _remove_shell_loader(self, shell):
        '''Remove our hookup for a shell: bash's ~/.bash_aliases link, or zsh's rc block. Leaves the
        conf.d dir + any snippet content alone.'''
        if shell == 'bash':
            self._remove_bash_aliases()
            return
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

    def _loader_ok(self, shell):
        '''True if `shell`'s loader is fully hooked: dir present, plus bash's ~/.bash_aliases link /
        the rc block for the rc-driven shells (zsh/elvish/nushell) where those apply (fish needs only
        the dir).'''
        if not self._confd(shell).is_dir():
            return False
        if shell == 'bash':
            return (self._home() / '.bash_aliases').is_symlink()
        rc_rel = _SHELL_RC.get(shell)
        if rc_rel is not None and not self._rc_has_block(self._expand(rc_rel)):
            return False
        return True

    def _pairs(self, rc):
        '''[(source_path, target_path)] resolved for this machine (snippet specs only).'''
        return [(self._resolve(src, rc)[0], self._expand(dst)) for _n, src, dst in self._specs(rc)]

    # -- read -------------------------------------------------------------

    def _deployed(self, dst, src, rc):
        '''The file a snippet's dst should resolve to when active — the machine-local store DEPLOY
        copy if present, else the resolved source (covers the dir-symlinked-conf.d / no-store cases).
        The `src` (authoritative source) and the deployed store copy live at different paths, so the
        "linked" check compares dst against THIS, not the source.'''
        store = self._glue_store(dst)
        if store is not None and store.exists():
            return store
        return self._resolve(src, rc)[0]

    def _drifted(self, srcpath, dst):
        '''True when a snippet's deployed store copy differs from its authoritative source — the repo/
        plugin shipped a CHANGED snippet since it was activated, so a re-activate is needed to pull it.
        Only meaningful for an active snippet backed by a store copy distinct from the source.'''
        store = self._glue_store(dst)
        if store is None or not store.is_file() or not srcpath.is_file():
            return False
        try:
            return store.read_bytes() != srcpath.read_bytes()
        except OSError:
            return False

    def get_version(self, rc):
        '''"linked" when every snippet's dst resolves to the managed store copy (or, for a loader
        component, every hooked shell's loader is in place); else None (not active).'''
        loaders = self._loader_shells(rc)
        if loaders:
            return 'linked' if all(self._loader_ok(s) for s in loaders) else None
        specs = self._specs(rc)
        if not specs:
            return None
        for _name, src, dst in specs:
            ref = self._deployed(dst, src, rc)
            tgt = self._expand(dst)
            if not (ref.exists()
                    and os.path.realpath(str(tgt)) == os.path.realpath(str(ref))):
                return None
        return 'linked'

    def spec_states(self, rc):
        '''[(name, target_display, state, src_root, src_rel, here, kind)] for status views. `kind`
        is always 'glue'. A loader component yields one row per hooked shell (loader-on/off).'''
        out = []
        for shell in self._loader_shells(rc):
            state = 'loader-on' if self._loader_ok(shell) else 'loader-off'
            out.append((f'{shell} loader', self.display_path(self._confd(shell)), state,
                        None, '', state == 'loader-on', 'glue'))
        for name, src, dst in self._specs(rc):
            srcpath, tier, root = self._resolve(src, rc)   # authoritative source (the SRC column)
            tgt = self._expand(dst)
            ref = self._deployed(dst, src, rc)
            if ref.exists() and os.path.realpath(str(tgt)) == os.path.realpath(str(ref)):
                # active: dst -> deployed copy. If the shipped source has since CHANGED, flag it as
                # drifted (active but stale) so the user knows to re-activate and pull the update.
                state = 'drifted' if self._drifted(srcpath, dst) else 'linked'
                src_root, here = root, True
            elif tier in ('user', 'template'):
                state, src_root, here = 'template', root, True   # source shipped but not linked -> available
            else:
                state, src_root, here = 'empty', self._defining_root(rc), False
            try:
                rel = str(srcpath.relative_to(src_root)) if here else src
            except ValueError:
                rel = src
            out.append((name, self.display_path(tgt), state, src_root, rel, here, 'glue'))
        return out

    def warnings(self, rc):
        return []                                          # glue is shipped content — nothing to adopt

    def get_latest(self, rc):
        return None

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    @staticmethod
    def _shell_of(spec_name):
        '''The shell a snippet spec belongs to (its `glue@<shell>` suffix), or None.'''
        return spec_name.rsplit('@', 1)[1] if '@' in spec_name else None

    def install(self, rc, only_shells=None):
        '''Activate `rc`'s glue. `only_shells` (a set/list of shell names) scopes the op to just those
        shells — the TUI passes it so activating a snippet in one shell group doesn't light up the
        component's OTHER shells (each per-shell row is independently activatable). None = all shells
        (the CLI install path).'''
        loaders = self._loader_shells(rc)
        if only_shells is not None:
            loaders = [l for l in loaders if l in only_shells]
        if loaders:                                        # a loader component (loader: zsh | all)
            for shell in loaders:
                self._ensure_shell_loader(shell, rc)
            return Result(f'glue: conf.d loader hooked up ({", ".join(loaders)})', 0)
        specs = self._specs(rc)
        if only_shells is not None:
            specs = [s for s in specs if self._shell_of(s[0]) in only_shells]
        if not specs:
            return Result(f'glue: {rc.comp} has no snippet for any installed shell', 0, advisory=True)
        # Deploy each snippet into the machine-local store MIRROR (<store>/<shell>/conf.d/),
        # executable, so the loader sources it and a link never references the repo. `refresh=True`
        # re-caches a store copy that has drifted from its (updated) authoritative source.
        pairs, shells, updated = [], set(), 0
        for name, src, dst in specs:
            srcpath, _tier, _root = self._resolve(src, rc)
            store = self._glue_store(dst) or srcpath
            if store != srcpath and store.is_file() and srcpath.is_file():   # drift check vs source
                try:
                    if store.read_bytes() != srcpath.read_bytes():
                        updated += 1
                except OSError:
                    pass
            self._materialize_to(srcpath, store, executable=True, refresh=True)
            sh = name.rsplit('@', 1)[1] if '@' in name else None
            if sh:
                shells.add(sh)
            pairs.append((srcpath, src, store, self._expand(dst)))
        lines = ['set -e']
        for _srcpath, src, link_src, tgt in pairs:
            # If conf.d is itself a dir-symlink to the store, the store file IS the deployed file;
            # linking would resolve to a self-link (ELOOP). Skip when realpaths already coincide.
            try:
                if link_src != tgt and os.path.realpath(str(link_src)) == os.path.realpath(str(tgt)):
                    continue
            except OSError:
                pass
            s, t = shlex.quote(str(link_src)), shlex.quote(str(tgt))
            lines.append(f'if [ -e {s} ]; then')
            lines.append(f'  mkdir -p {shlex.quote(str(tgt.parent))}')
            lines.append(f'  ln -sfn {s} {t}')
            lines.append(f'else echo "glue: {rc.comp} not populated ({src} absent)" >&2; fi')
        res = self.runner.run('\n'.join(lines), capture=False)
        if res is not None and not res.ok:
            return res
        # Ensure the conf.d LOADER is wired for each shell this snippet deploys to, so it actually
        # sources — checked on every install AND update (upgrade == install). The snippet's own
        # `requires: shell-glue` covers the CLI pipeline, but a direct activate (TUI) bypasses it.
        for shell in shells:
            self._ensure_shell_loader(shell, rc)
        msg = f'activated {rc.comp}'
        if updated:
            msg += f' ({updated} snippet(s) refreshed from source)'
        return Result(f'glue install {rc.comp}', 0, stdout=msg)   # msg rides in stdout -> res.output

    def upgrade(self, rc):
        return self.install(rc)                             # idempotent re-link

    def set_version(self, rc, version):
        return self.install(rc)

    def uninstall(self, rc, only_shells=None):
        '''Deactivate `rc`'s glue. `only_shells` scopes it to those shells (the TUI deactivates one
        shell group's row without touching the component's other shells); None = all shells.'''
        loaders = self._loader_shells(rc)
        if only_shells is not None:
            loaders = [l for l in loaders if l in only_shells]
        if loaders:
            for shell in loaders:
                self._remove_shell_loader(shell)           # drop the rc block; leave conf.d + content
            return Result(f'glue: conf.d loader removed ({", ".join(loaders)})', 0)
        specs = self._specs(rc)
        if only_shells is not None:
            specs = [s for s in specs if self._shell_of(s[0]) in only_shells]
        if not specs:
            return Result(f'glue: {rc.comp} has no snippet to remove', 0, advisory=True)
        lines = []
        for _name, _src, dst in specs:
            t = shlex.quote(str(self._expand(dst)))
            lines.append(f'if [ -L {t} ]; then rm -f {t}; fi')  # only our own symlink
        res = self.runner.run('\n'.join(lines), capture=False)
        # inline (gestalt) shells snapshot conf.d into the rc block — regenerate it after removing
        # this snippet's file(s) so its content doesn't linger in the block.
        for shell in {self._shell_of(n) for n, _s, _d in specs} & set(_INLINE_SHELLS):
            self._ensure_shell_loader(shell)
        return res

    def location(self, rc):
        loaders = self._loader_shells(rc)
        if loaders:
            return '; '.join(self.display_path(self._confd(s)) for s in loaders)
        targets = [self.display_path(tgt) for _src, tgt in self._pairs(rc)]
        return '; '.join(targets) if targets else None

    def lock(self, rc):
        return Result('(glue lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(glue unlock recorded in ledger)', 0)
