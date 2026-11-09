'''glue.py — the glue driver: shell-integration enablement (`via: glue`).

Glue is the shell wiring a component needs to be USABLE — PATH, aliases, env, completions,
shell init — deployed as small snippets under the uniform `<config>/<shell>/conf.d/` dir (`<config>` =
`~/.config` for bash/zsh; `$XDG_CONFIG_HOME`, default `~/.config`, for fish/nushell/elvish, which
read their own config there — configsys/shells.py), plus
the per-shell LOADERS that make each shell source that dir. It is the sibling of the dotfiles
driver (`via: dotfiles`), which manages a component's own reposited CONFIG. The two were one driver
historically; they are split so each is its own concern (each with its own TUI screen).

A `via: glue` binding is one of:
  * `glue: <name>`   — a snippet: link `shell/<shell>/<name>.<ext>` into
                       `<config>/<shell>/conf.d/50-<name>.<ext>`, for each INSTALLED shell that ships
                       a variant. Snippets deploy through the machine-local store MIRROR (never
                       linking the repo).
  * `loader: <shell>`— hook one shell up to source its conf.d (bash and zsh get an rc marker-block;
                       fish auto-sources natively; elvish/nushell inline the snippets into the rc —
                       they can't dynamically source a dir).

User-space only (no sudo); no version — glue is "active" or not. Spec: docs/shell-glue.md (loaders,
the conf.d load-order bands 00-/50-/90-/99-, user.d, overrides, the shell-writes guard).

Storage is SEGREGATED from the dotfiles driver: glue authoring lives at `glue/shell/<shell>/
<name>.<ext>` (repo/plugin), materializes into the machine-local glue store `<state>/glue/<shell>/
conf.d/<name>.<ext>`, and links into `~/.config/<shell>/conf.d/`. The dotfiles driver's `dotfiles/`
tree (config `*.cfs/` captures) and this `glue/` tree never share a directory.

TRUST: every snippet is code — your shells source it at every start, and a `#!cs-eval` generator
runs a command inside configsys at (de)activation. So: a plugin's glue deploys only when that plugin
is trusted (`command_trusted`, and a primary override / a primary user.d snippet by the primary's
`primary-trust:` — `_source_trusted`); a generator runs only from a conf.d file that resolves into a
glue root configsys owns, only when its directive sits in the file's leading comment header, and
only for `_EVAL_TIMEOUT` seconds. conf.d itself is configsys's dir: whoever can write it can write
your rc too, so a foreign file there is inlined as text but never run as a generator.
'''

import hashlib
import json
import os
import re
import shlex
import shutil
from pathlib import Path

from .. import primarygit
from ..shells import SHELLS
from ..driver import Driver
from ..runner import Result
from . import _linked

_VAR = re.compile(r'\$[A-Za-z_][A-Za-z0-9_]*')
BACKUP_SUFFIX = '.pre-configsys'
# bash once rode the Debian-only `~/.bash_aliases` convention (a link to the shipped `bash_aliases`
# loader's store copy); it is a ~/.bashrc block now (B3), and only OUR old link is retired.
_BASH_ALIASES_SRC = 'bash_aliases'

# Per-shell facts come from ONE table, configsys/shells.py (a ShellSpec row per shell); these are
# its views. A shell activates the moment a snippet variant for it exists.
_SHELL_EXT = {n: s.ext for n, s in SHELLS.items()}            # a snippet's file extension
_SHELL_CONFD = {n: s.confd for n, s in SHELLS.items()}        # the dir its loader sources
_GLUE_SHELLS = tuple(SHELLS)

# The component-INDEPENDENT user-glue namespace: snippets under `<glue-root>/shell/<shell>/user.d/`
# that the driver ALWAYS deploys into conf.d — the user's OWN startup, linked from the layer and
# edited in the layer (portable when the layer is the primary plugin). `99-user` is the auto-scaffolded
# home; the `99-` prefix loads it AFTER component glue so the user's aliases win. (docs/done/glue-customization-plan.md P0)

# conf.d LOAD ORDER (docs/shell-glue.md): every loader sources conf.d in lexical order, so the link
# NAME is the order. Three bands: `00-` the configsys prelude (its glue name already carries the
# prefix) -> `50-` component glue -> `90-` user glue (user.d snippets: `glue add`, activated staged
# blocks), with the blessed `99-user` home last. A name that already starts with a two-digit `NN-`
# keeps it (00-configsys, 99-user, a user's deliberate `10-early`). Links made before the bands
# existed (unprefixed `<name>.<ext>`) are no longer migrated (§7.16) — `check` names any left
# (legacy_links); anything else in conf.d is never touched.
_ORDER_PREFIX = re.compile(r'^\d\d-')
COMPONENT_PREFIX = '50-'
USER_PREFIX = '90-'


def component_link_stem(glue):
    '''The conf.d link stem of a component's `glue: <name>` (`bat` -> `50-bat`; `00-configsys` kept).'''
    return glue if _ORDER_PREFIX.match(glue) else f'{COMPONENT_PREFIX}{glue}'


def user_link_name(filename):
    '''The conf.d link name of a user.d snippet file (`foo.sh` -> `90-foo.sh`; `99-user.sh` kept).'''
    return filename if _ORDER_PREFIX.match(filename) else f'{USER_PREFIX}{filename}'
_USER_GLUE_HEADER = (
    '# Your own shell startup. configsys links this into conf.d but NEVER edits its contents.\n'
    '# Add aliases / env / functions below — they load after component glue, so yours win.\n'
    '# Keep it in your primary plugin (or use `configsys glue add`) to share it across machines.\n')

# the component that INSTALLS each shell (for the managed-install detection) — identity except nu.
_SHELL_COMPONENT = {n: s.component for n, s in SHELLS.items() if s.component != n}

# loaders (`loader: <shell>`): hook a shell up to run its <config>/<shell>/conf.d/* snippets.
# fish auto-sources conf.d natively (no rc edit); bash and zsh need one configsys-owned,
# marker-delimited rc block that SOURCES the dir; elvish and nushell are INLINE (see below). The markers make the block idempotent + cleanly removable.
_RC_BEGIN = '# >>> configsys glue >>>'
_RC_END = '# <<< configsys glue <<<'
_SHELL_RC = {n: s.rc for n, s in SHELLS.items() if s.rc}
# a login bash reads the first of these; where none exists, one that sources ~/.bashrc is written
# (Void/Alpine ship no skel profile), so a login shell gets the glue too
_BASH_PROFILES = ('~/.bash_profile', '~/.bash_login', '~/.profile')
_BASH_PROFILE_BODY = '[ -f ~/.bashrc ] && . ~/.bashrc'

# GESTALT (inline) shells: neither elvish nor nushell can dynamically source a dir of snippets into
# the interactive scope. Elvish's per-file `eval` ISOLATES namespaces (a sourced file's `fn`/`var`
# defs never reach the interactive shell). Nushell parses the WHOLE program before running, so
# `source` is a parse-time keyword whose path must be a compile-time constant — you can't loop-source
# conf.d at all. For both, the rc marker block INLINES the concatenated conf.d snippet contents
# directly (so definitions land in the interactive scope), regenerated on every (de)activation. It's
# also faster — one block, not N sourced files. (Consequence: an inline-rc shell's rc is glue-owned
# and cannot be a dotfiles capture — capturing freezes the block — so these shells have no -dotfiles.)
_INLINE_SHELLS = tuple(n for n, s in SHELLS.items() if s.mode == 'inline')

# A `#!cs-eval <cmd>` line makes a snippet a GENERATOR: the inline loader runs <cmd> at (de)activation
# and inlines its stdout (an init-eval tool's shell code) instead of the snippet text — the bridge for
# tools like zoxide/atuin on nushell, which has no runtime source/eval. Self-guards: a failing command
# inlines nothing. Honored only in the file's leading comment header, in a file inside a glue root
# configsys owns, and cut off after _EVAL_TIMEOUT seconds (a hung init must not hang the TUI).
_EVAL_DIRECTIVE = re.compile(r'^#!\s*cs-eval\s+(.+?)\s*$')
_EVAL_TIMEOUT = 10

# _installed_shells' answer per detection key (PATH + each PATH dir's mtime + the managed shell dirs
# and their mtimes): a new binary changes its dir's mtime, so the memo never goes stale, yet a status
# pass over every glue component costs a few stats instead of 5 `which` walks + globs per name.
_SHELLS_MEMO = {}

# GLUE speaks a binary vocabulary (active/available/inactive) — a ship->activate toggle. This maps
# the underlying spec/loader states to those labels (identity for anything unlisted). Shared by the
# TUI and the CLI status so they never diverge.
GLUE_STATE_LABEL = {'linked': 'active', 'loader-on': 'active', 'drifted': 'changed',
                    'template': 'available', 'loader-off': 'inactive'}
# how each rc-driven shell sources its conf.d dir (empty-glob-safe).
_RC_SOURCE = {
    # bash: -r, not -x (a snippet loads whether or not it carries the exec bit); an empty dir leaves
    # the literal glob, which -r rejects
    'bash': ('for _f in {confd}/*.sh; do [ -r "$_f" ] && . "$_f"; done\n'
             'unset _f'),
    # zsh: the (N) glob qualifier = null_glob for THIS glob only (a `setopt local_options null_glob` at
    # rc top level isn't local to anything — it leaked null_glob into your session; B13)
    'zsh': ('for _f in {confd}/*.zsh(N); do source "$_f"; done\n'
            'unset _f'),
}


def _mtime(path):
    '''`path`'s mtime (ns), or None when it can't be stat'ed — a memo-key ingredient.'''
    try:
        return os.stat(path).st_mtime_ns
    except (OSError, ValueError):
        return None


def _read_rc(path):
    '''An rc file's text with every byte preserved (a Latin-1 comment, CRLF) — `_write_rc` puts it back.'''
    return Path(path).read_bytes().decode('utf-8', 'surrogateescape')


def _write_rc(path, text):
    Path(path).write_bytes(text.encode('utf-8', 'surrogateescape'))


class Glue(Driver):
    name = 'glue'
    targets_version = False   # glue has no version
    notes_in_stdout = True    # install/uninstall stdout is human notes (activated, moved aside, …)
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
        stem = component_link_stem(glue)
        return [(f'{glue}@{shell}', src, f'{_SHELL_CONFD[shell]}/{stem}.{ext}')
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
        path = env.get('PATH')
        search = path if path is not None else os.environ.get('PATH', os.defpath)
        dirs = self._managed_shell_dirs()
        key = (search, tuple((d, _mtime(d)) for d in search.split(os.pathsep)),
               tuple((s, str(d), _mtime(d)) for s, d in dirs))
        hit = _SHELLS_MEMO.get(key)
        if hit is not None:
            return list(hit)
        on_path = {s for s in _GLUE_SHELLS if shutil.which(s, path=path)}
        managed = {s for s, d in dirs if self._shell_binary_in(s, d)}
        found = [s for s in _GLUE_SHELLS if s in on_path or s in managed]   # _GLUE_SHELLS order, deduped
        if len(_SHELLS_MEMO) > 64:
            _SHELLS_MEMO.clear()
        _SHELLS_MEMO[key] = tuple(found or ['bash'])
        return list(_SHELLS_MEMO[key])

    def _managed_shell_dirs(self):
        '''[(shell, dir)] — each glue shell's managed install dir from the glue-locations cache
        (component -> dir), whether or not its binary is there yet. A shell whose binary IS there counts
        as installed: a tarball shell is glue-managed before a fresh shell puts it on PATH. Empty when
        the cache is cold (PATH detection alone).'''
        locs = self._read_location_cache()
        out = []
        for shell in _GLUE_SHELLS:
            d = locs.get(_SHELL_COMPONENT.get(shell, shell))
            if d:
                out.append((shell, self._expand(d)))
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
        template) carrying the `shell/<shell>/<name>.<ext>` authoring
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
            chosen = None
            for root, _tier in self._content_roots(rc):    # store, primary plugin, then repo template
                for src in auth:
                    if (root / src).exists():
                        chosen = src
                        break
                if chosen:
                    break
            if chosen is None:                             # fallback: an existing store deploy mirror
                for mirror in (f'{shell}/conf.d/{component_link_stem(glue)}.{ext}',):
                    for root, _tier in self._content_roots(rc):
                        if (root / mirror).exists():
                            chosen = mirror
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

    # -- user-glue namespace (component-independent; docs/done/glue-customization-plan.md P0) ------------

    def _user_glue_roots(self):
        '''Glue roots that can hold the user.d namespace, HIGHEST precedence first: the machine-local
        store, then the primary plugin. (The repo ships no user.d — it is user content.)'''
        roots = []
        p = self.paths
        if p is not None:
            for attr in ('user_glue_dir', 'primary_glue_dir'):
                d = getattr(p, attr, None)
                if d is not None:
                    roots.append(Path(d))
        return roots

    def _dest_glue_root(self, local=False):
        '''Where a NEW user snippet is written: the primary plugin's glue root when one is configured
        (its glue/ dir exists) and not `local`, so it travels; else the machine-local store. None if
        neither exists.'''
        p = self.paths
        if p is None:
            return None
        prim = getattr(p, 'primary_glue_dir', None)
        if prim is not None and not local:
            return Path(prim)
        u = getattr(p, 'user_glue_dir', None)
        return Path(u) if u is not None else None

    @staticmethod
    def _user_d(root, shell):
        return root / 'shell' / shell / 'user.d'

    def new_user_snippet(self, name, shell, local=False):
        '''Create (if absent) a user.d snippet `<name>.<ext>` for `shell` in the destination glue root
        (primary plugin if set + not `local`, else the local store), with a small header (its mode is left
        to your umask — no loader needs the x bit, and a private snippet stays private). The
        front door for `configsys glue add`; the caller opens $EDITOR then deploys via
        `_ensure_shell_loader(shell)`. Returns (path, created), or (None, False) for an unknown shell /
        no store. A trailing `.<ext>` in `name` is stripped so `glue add foo` and `foo.sh` agree.'''
        ext = _SHELL_EXT.get(shell)
        if ext is None:
            return None, False
        dest = self._dest_glue_root(local=local)
        if dest is None:
            return None, False
        stem = name[:-(len(ext) + 1)] if name.endswith(f'.{ext}') else name
        path = self._user_d(dest, shell) / f'{stem}.{ext}'
        created = not path.exists()
        if created and getattr(self.runner, 'pretend', False):   # a dry run creates nothing
            return path, False
        if created:
            primarygit.will_write(path)                     # the glue root may be the primary's
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f'# {stem} — your own {shell} glue. configsys links this into conf.d but\n'
                            f'# never edits it; loads after component glue, so your definitions win.\n')
        return path, created

    def deploy_user_glue(self, shell):
        '''Public wrapper: hook up `shell` and (re)link its user.d namespace into conf.d — so a snippet
        just written by `glue add` is deployed (and inlined, for a gestalt shell) without a full op.
        What it left out lands in `self.hookup_warnings` / `self.inline_warnings`.'''
        self.inline_warnings, self.hookup_warnings = [], []
        return self._ensure_shell_loader(shell)

    def user_glue_link(self, shell, filename):
        '''The conf.d link a user.d snippet file deploys to (`foo.sh` -> ~/.config/bash/conf.d/90-foo.sh)
        — what `glue add` / `dotfiles activate` print. None for an unknown shell.'''
        if shell not in _SHELL_CONFD:
            return None
        return self._confd(shell) / user_link_name(Path(filename).name)

    def add_user_glue(self, name, shell, body, local=False):
        '''Write `body` as user glue `user.d/<name>.<ext>` (the same namespace + destination root as
        `glue add`: the primary plugin unless `local`, else the local store) and deploy it. The
        front door for turning a staged installer block into ordinary user glue
        (shellguard.activate). Never clobbers: an existing snippet that already contains `body` is
        left as is; otherwise `body` is APPENDED to it, so a user's edits survive a re-activation.
        Returns (snippet_path, conf.d_link), or (None, None) for an unknown shell / no store.'''
        if getattr(self.runner, 'pretend', False):
            return None, None
        path, created = self.new_user_snippet(name, shell, local=local)
        if path is None:
            return None, None
        text = body if body.endswith('\n') else body + '\n'
        try:
            cur = path.read_text()
        except OSError:
            cur = ''
        primarygit.will_write(path)
        if text.strip() not in cur:
            sep = '' if (not cur or cur.endswith('\n')) else '\n'
            path.write_text(f'{cur}{sep}{text}')
        self.deploy_user_glue(shell)
        return path, self.user_glue_link(shell, path.name)

    def user_glue_entries(self):
        '''[(shell, snippet_path, link_path, state)] for every user.d snippet in the user glue roots
        (local store wins over primary on a name clash), for each glue shell. `state` is 'linked'
        (its conf.d link resolves to the snippet) or 'unlinked' — the user-glue rows a status view
        (the Glue screen, `dotfiles status`) lists next to component glue.'''
        out = []
        for shell in _GLUE_SHELLS:
            ext = _SHELL_EXT[shell]
            seen = {}
            for root in self._user_glue_roots():
                d = self._user_d(root, shell)
                if d.is_dir():
                    for f in sorted(d.glob(f'*.{ext}')):
                        seen.setdefault(f.name, f)
            for fname, src in sorted(seen.items(), key=lambda kv: user_link_name(kv[0])):
                link = self.user_glue_link(shell, fname)
                try:
                    ok = link.is_symlink() and os.path.realpath(link) == os.path.realpath(src)
                except OSError:
                    ok = False
                out.append((shell, src, link, 'linked' if ok else 'unlinked'))
        return out

    # -- override a component's shipped glue (docs/done/glue-customization-plan.md P2) -------------------

    def _glue_names(self, rc):
        '''The glue name(s) a component ships (`glue:` top-level + nested).'''
        f, names = rc.fields, []
        if f.get('glue'):
            names.append(f['glue'])
        for v in f.values():
            if isinstance(v, dict) and v.get('glue'):
                names.append(v['glue'])
        return names

    def _shipped_glue_path(self, rc, shell, glue):
        '''The AUTHORITATIVE shipped snippet in the DEFINING layer (repo/plugin) — the thing an
        override forks from and the drift check re-hashes. Not a user root, not the deploy mirror.'''
        ext = _SHELL_EXT.get(shell)
        if ext is None:
            return None
        return self._defining_root(rc) / 'shell' / shell / f'{glue}.{ext}'

    def _overrides_file(self, root):
        return Path(root) / 'glue-overrides.json'

    def _load_overrides(self, root):
        '''{"<comp>|<shell>": forked-from-sha256} recorded in `root` (the glue root the override
        landed in), or {} if none/unreadable.'''
        try:
            data = json.loads(self._overrides_file(root).read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _record_override(self, root, comp, shell, digest):
        d = self._load_overrides(root)
        d[f'{comp}|{shell}'] = digest
        try:
            f = self._overrides_file(root)
            primarygit.will_write(f)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(d, sort_keys=True), encoding='utf-8')
        except OSError:
            pass

    def override(self, rc, shell=None, local=False):
        '''Fork this glue component's SHIPPED snippet(s) into the user's layer so they shadow the repo
        by content-root precedence. For each installed shell that ships a variant (optionally just
        `shell`): copy <defining-root>/shell/<shell>/<glue>.<ext> to <dest>/… (NEVER clobber an
        existing override), record the forked-from hash for the drift advisory, and collect the dest
        path. Deploy is the caller's `install(rc)` (which resolves the override via the search path).
        Returns [(dest_path, shell)]; empty if no store or no shipped variant.'''
        dest = self._dest_glue_root(local=local)
        if dest is None or getattr(self.runner, 'pretend', False):
            return []
        out = []
        for name, src, _dst in self._specs(rc):
            sh = self._shell_of(name)
            if sh is None or (shell is not None and sh != shell):
                continue
            glue = name.rsplit('@', 1)[0]
            shipped = self._shipped_glue_path(rc, sh, glue)
            if shipped is None or not shipped.is_file():
                continue
            target = Path(dest) / src
            if not target.exists():                        # never overwrite an existing override
                primarygit.will_write(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(shipped, target)
            self._record_override(dest, rc.comp, sh, hashlib.sha256(shipped.read_bytes()).hexdigest())
            out.append((target, sh))
        return out

    def override_drift(self, rc):
        '''[(shell, forked_hash, current_hash)] for this component's recorded overrides whose SHIPPED
        source has since changed (forked != current) — the drift advisory `check` surfaces. Reads the
        overrides manifest from every glue root; a source that no longer exists is skipped.'''
        drift = []
        for root in self._user_glue_roots():
            recorded = self._load_overrides(root)
            for glue in self._glue_names(rc):
                for shell in _GLUE_SHELLS:
                    digest = recorded.get(f'{rc.comp}|{shell}')
                    if digest is None:
                        continue
                    shipped = self._shipped_glue_path(rc, shell, glue)
                    if shipped is None or not shipped.is_file():
                        continue
                    cur = hashlib.sha256(shipped.read_bytes()).hexdigest()
                    if cur != digest:
                        drift.append((shell, digest, cur))
        return drift

    # -- ownership: configsys's glue roots and conf.d links (+ legacy unprefixed links) ---------

    def _owned_glue_roots(self, rc=None):
        '''Every glue root configsys owns content in: the machine-local store, the primary plugin's
        glue/, the repo glue/, and (for a component) its defining layer's glue/.'''
        roots = []
        p = self.paths
        if p is not None:
            for attr in ('user_glue_dir', 'primary_glue_dir', 'glue_dir'):
                d = getattr(p, attr, None)
                if d is not None:
                    roots.append(Path(d))
        if rc is not None:
            roots.append(self._defining_root(rc))
        return roots

    def _link_into_owned(self, link, rc=None, user_d=None):
        '''True when `link` is a symlink whose target lies inside a glue root configsys owns.
        `user_d=True` additionally requires the target to be a user.d snippet, `False` forbids it
        (a component's legacy link vs a user snippet's). Judged on the link TEXT (normalized) and on
        its realpath, so a link whose target was just renamed away still counts. Never raises.'''
        try:
            if not link.is_symlink():
                return False
            raw = Path(os.readlink(link))
        except OSError:
            return False
        if not raw.is_absolute():
            raw = link.parent / raw
        cands = {Path(os.path.normpath(str(raw))), Path(os.path.realpath(str(link)))}
        if user_d is not None and any(('user.d' in c.parts) != user_d for c in cands):
            return False
        for root in self._owned_glue_roots(rc):
            for r in {Path(os.path.normpath(str(root))), Path(os.path.realpath(str(root)))}:
                if any(c == r or r in c.parents for c in cands):
                    return True
        return False

    def legacy_links(self):
        """[(link, target)] — unprefixed links in a shell's conf.d that point into a glue root
        configsys owns: deployments from before the load-order bands. Read-only: they are no longer
        migrated (review-2026-11-2 §7.16); `check` names them so you can delete each (the banded
        `50-`/`90-` link loads the same snippet)."""
        out = []
        for shell in _GLUE_SHELLS:
            confd = self._confd(shell)
            try:
                entries = sorted(confd.iterdir()) if confd.is_dir() else []
            except OSError:
                continue
            for link in entries:
                if _ORDER_PREFIX.match(link.name) or not link.is_symlink():
                    continue
                if self._link_into_owned(link):
                    try:
                        out.append((link, os.readlink(link)))
                    except OSError:
                        pass
        return out

    def _deploy_user_glue(self, shell):
        '''Deploy the user-glue namespace for `shell`: scaffold the blessed 99-user home the first time
        (when NO user.d dir exists yet in any root — so emptying it doesn't resurrect it), then link
        every user.d snippet (local root wins over primary) into <config>/<shell>/conf.d/. conf.d
        shells source these; the inline/gestalt shells inline them (the block reads all of conf.d).
        Links point straight at the layer file so editing the linked snippet edits the (portable)
        source — the layers idea. A snippet's mode is never touched (no loader needs the x bit). Our
        user-band link whose snippet is gone (deleted, or synced away) is pruned, and a snippet from a
        primary that `primary-trust:` doesn't trust right now is not linked (its link, if any, goes;
        named in `self.hookup_warnings`). Idempotent; runs on every shell hookup.'''
        self.hookup_warnings = []
        ext = _SHELL_EXT.get(shell)
        if ext is None:
            return
        roots = self._user_glue_roots()
        if not any(self._user_d(r, shell).is_dir() for r in roots):     # scaffold once
            dest = self._dest_glue_root()
            if dest is not None:
                d = self._user_d(dest, shell)
                d.mkdir(parents=True, exist_ok=True)
                home = d / f'99-user.{ext}'
                if not home.exists():
                    primarygit.will_write(home)
                    home.write_text(_USER_GLUE_HEADER)
                if dest not in roots:
                    roots.append(dest)
        snippets = {}
        for r in roots:
            d = self._user_d(r, shell)
            if d.is_dir():
                for f in sorted(d.glob(f'*.{ext}')):
                    snippets.setdefault(f.name, f)                       # first (local) root wins
        ours = lambda d: self._link_into_owned(d, user_d=True)          # noqa: E731 — a user.d link of ours
        confd = self._ensure_confd(shell) if snippets else self._confd(shell)
        trust = {}
        for name, srcpath in snippets.items():
            tgt = confd / user_link_name(name)                           # the user band (90-, or NN- kept)
            if not self._source_trusted(srcpath, trust):
                self.hookup_warnings.append(f'{shell}: your user glue {name} is not linked — '
                                            f'{self._untrusted_why(srcpath)}')
                _linked.unlink(self.runner, tgt, ours=ours)              # an earlier link to it goes too
                continue
            _linked.link(self.runner, srcpath, tgt, ours=self._link_into_owned)   # your file kept aside
        try:
            entries = sorted(confd.iterdir()) if confd.is_dir() else []
        except OSError:
            entries = []
        for link in entries:                                             # prune: the snippet is gone
            if link.is_symlink() and not link.exists() and ours(link):
                _linked.unlink(self.runner, link, ours=ours)             # (a foreign dangling link stays)

    def _source_trusted(self, path, memo=None):
        '''Whether a glue file at `path` may go live: True for the repo, the local store and your own
        config; a file inside a synced plugin (your primary included, per `primary-trust:`) only when
        that plugin's current content is trusted — plugins.command_source_trusted. `memo` ({plugin:
        bool}) saves re-hashing one plugin per snippet. No paths (unit tests) = trusted.'''
        p = self.paths
        if p is None or getattr(p, 'plugins_dir', None) is None:
            return True
        from .. import plugins
        name = plugins.plugin_of_source(p, str(path))
        if name is None:
            return True
        if memo is None:
            memo = {}
        if name not in memo:
            memo[name] = plugins.command_source_trusted(p, str(path))
        return memo[name]

    def _untrusted_why(self, path):
        '''The reason + remedy for an untrusted glue file (names its plugin).'''
        from .. import plugins
        name = plugins.plugin_of_source(self.paths, str(path)) if self.paths is not None else None
        return (f'it comes from the plugin {name or "?"!r}, which is not trusted at its current content '
                f'— review it, then `configsys plugin trust {name or "<plugin>"}`')

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
        source is safe and desired). With `executable`, set a+x on the result (shipped content only —
        no loader needs it, the store copy just keeps the historical mode; a user's own snippet is
        never chmod'ed). Returns dest (or srcpath if there's nothing to copy / no dest).'''
        if dest is None or not srcpath.exists():
            return srcpath
        if getattr(self.runner, 'pretend', False):         # --pretend must not touch the store
            return dest
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
        '''The machine-local glue-store MIRROR of a snippet dst: <config>/<shell>/conf.d/<x> maps to
        <glue-store>/<shell>/conf.d/<x>, so the store lines up with the deployed layout (and links are
        uniform, never the repo). `<config>` is $XDG_CONFIG_HOME (fish/nushell/elvish read theirs
        there) or ~/.config (bash/zsh). None if there's no store or the dst is under neither.'''
        store = getattr(self.paths, 'user_glue_dir', None) if self.paths is not None else None
        if store is None:
            return None
        tgt = self._expand(dst)
        for base in (self._expand('$XDG_CONFIG_HOME'), self._home() / '.config'):
            try:
                return Path(store) / tgt.relative_to(base)
            except ValueError:
                continue
        return None

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
        instead of its text (the init-eval bridge — see _generator); a file that isn't configsys's is
        inlined as text, never run.'''
        ext = _SHELL_EXT[shell]
        confd = self._confd(shell)
        parts = []
        if confd.is_dir():
            for f in sorted(confd.iterdir()):              # 00- first -> substrate defines helpers early
                if not f.name.endswith(f'.{ext}'):
                    continue
                try:
                    content = f.read_text(errors='replace')
                except OSError:
                    continue
                cmd = self._generator(f, content)
                if cmd is not None:                        # a generator snippet: inline the cmd's stdout
                    out = self._run_eval(cmd)
                    if out.strip():
                        parts.append(f'# >> {f.name} (generated: {cmd})\n{out.rstrip(chr(10))}')
                    # a tool that's absent / too old to emit a nu init -> nothing inlined (self-guard)
                else:
                    parts.append(f'# >> {f.name}\n{content.rstrip(chr(10))}')
        parts = self._valid_parts(shell, parts)
        body = '\n\n'.join(parts)
        return f'{_RC_BEGIN}\n# cs-inputs: {self._inline_inputs(shell)}\n{body}\n{_RC_END}\n'

    def _inline_inputs(self, shell):
        '''A hash of what an inline block is built FROM — each conf.d snippet's text, and for a
        generator snippet its command's binary (path + mtime, so a tool upgrade counts) — without
        running any generator. Stored in the block; a different value now means the block is a stale
        snapshot (a user.d edit, a primary sync, an upgraded zoxide) and the loader reads `off`.'''
        ext = _SHELL_EXT[shell]
        confd = self._confd(shell)
        h = hashlib.sha256()
        try:
            entries = sorted(confd.iterdir()) if confd.is_dir() else []
        except OSError:
            entries = []
        for f in entries:
            if not f.name.endswith(f'.{ext}'):
                continue
            try:
                content = f.read_text(errors='replace')
            except OSError:
                continue
            h.update(f.name.encode() + b'\0' + content.encode('utf-8', 'replace') + b'\0')
            cmd = self._generator(f, content)
            if cmd:
                tool = shutil.which(cmd.split()[0]) if cmd.split() else None
                try:
                    stamp = f'{tool}:{os.stat(tool).st_mtime_ns}' if tool else 'absent'
                except OSError:
                    stamp = 'absent'
                h.update(stamp.encode() + b'\0')
        return h.hexdigest()[:16]

    def _inline_current(self, shell, rc_path):
        '''True when the inline block in `rc_path` was built from what conf.d holds now.'''
        try:
            text = Path(rc_path).read_text(errors='replace')
        except OSError:
            return False
        m = re.search(r'^# cs-inputs: (\w+)$', text, re.M)
        return bool(m) and m.group(1) == self._inline_inputs(shell)

    # the shell's own parse-only check: nushell parses the WHOLE program before running any of it, so
    # one bad snippet (or a generator's output from an incompatible tool version) disables every
    # line of config.nu, PATH included — validate before writing (review-2026-11-2 A15)
    _CHECKERS = {'nu': ("nu --no-config-file -c 'if (nu-check {f}) {{ exit 0 }} else {{ exit 1 }}'", 'nu'),
                 'elvish': ('elvish -compileonly {f}', 'elvish')}

    def _valid_parts(self, shell, parts):
        '''`parts` minus any snippet that makes the block fail the shell's parse check — checked whole
        first (one spawn); only on a failure snippet by snippet, keeping what still parses. Without
        the shell binary (or under --pretend) nothing is checked. Dropped ones are named in
        `self.inline_warnings`.'''
        self.inline_warnings = []
        spec = self._CHECKERS.get(shell)
        if spec is None or not parts or getattr(self.runner, 'pretend', False) or not shutil.which(spec[1]):
            return parts
        import tempfile

        def ok(chunk):
            with tempfile.NamedTemporaryFile('w', suffix=f'.{_SHELL_EXT[shell]}', delete=False) as tf:
                tf.write('\n\n'.join(chunk) + '\n')
            try:                                           # a read-only parse probe (not an op)
                import subprocess
                r = subprocess.run(['bash', '-c', spec[0].format(f=shlex.quote(tf.name))],
                                   stdin=subprocess.DEVNULL, capture_output=True, timeout=20)
                return r.returncode == 0
            except (OSError, subprocess.SubprocessError):
                return True                                # can't check: don't drop anything
            finally:
                os.unlink(tf.name)
        if ok(parts):
            return parts
        kept = []
        for part in parts:
            if ok(kept + [part]):
                kept.append(part)
            else:
                name = part.splitlines()[0][len('# >> '):] if part.startswith('# >> ') else '?'
                self.inline_warnings.append(f'{shell}: {name} left out of the inline block — it does '
                                            f'not parse with this {spec[1]} (fix or remove it)')
        return kept

    def _eval_directive(self, content):
        '''The `<cmd>` of a `#!cs-eval <cmd>` line in a snippet's leading comment header (a GENERATOR
        snippet), else None — a directive after the first line of code is just a comment. Used for
        init-eval tools (zoxide/atuin) on a shell with no runtime `source`/eval: the driver runs the
        command at (de)activation and inlines its stdout into the gestalt block.'''
        for line in content.splitlines():
            s = line.strip()
            if s and not s.startswith('#'):
                return None                                # past the header: code, not a directive
            m = _EVAL_DIRECTIVE.match(s)
            if m:
                return m.group(1).strip()
        return None

    def _generator(self, f, content):
        '''The generator command of conf.d file `f` — only when the file resolves into a glue root
        configsys owns (the store, your primary's glue/, the repo's): a file anything else dropped in
        conf.d is inlined as text, never run.'''
        cmd = self._eval_directive(content)
        if cmd is None:
            return None
        return cmd if any(_linked.inside(f, r) for r in self._owned_glue_roots()) else None

    def _run_eval(self, cmd):
        '''Run a generator snippet's command, returning its stdout ('' on ANY failure — a tool that's
        absent or too old to emit a nu/elvish init must never break the block; one that hangs is cut
        off after _EVAL_TIMEOUT seconds).'''
        try:
            r = self.runner.run(cmd, capture=True, timeout=_EVAL_TIMEOUT)
        except Exception:                                  # noqa: BLE001 — a flaky init must not brick glue
            return ''
        return (r.stdout or '') if (r is not None and r.ok) else ''

    def _rc_has_block(self, rc_path):
        try:
            return _RC_BEGIN in Path(rc_path).read_text(errors='replace')
        except (FileNotFoundError, OSError):
            return False

    def _ensure_shell_loader(self, shell, rc=None):
        '''Idempotent hookup for a shell's conf.d loader. Always ensures the dir; bash and zsh
        insert/refresh ONE configsys-owned marker block that SOURCES the dir; elvish and nushell (gestalt/inline shells) insert/refresh a
        marker block that INLINES the concatenated conf.d snippets (_inline_block); fish (native
        auto-source) gets the dir only. Returns True if a hookup is in place for this shell.'''
        if getattr(self.runner, 'pretend', False):         # --pretend: report hooked, write nothing
            return True
        self._ensure_confd(shell)
        self._record_launcher()                            # where the preludes' `configsys`/`cfs` run
        self._deploy_user_glue(shell)                      # scaffold + link the user.d namespace
        rc_rel = _SHELL_RC.get(shell)
        if rc_rel is None:                                 # fish (native conf.d): dir is the whole job
            return True
        rc_path = self._expand(rc_rel)
        if rc_path.is_symlink():                            # a captured/managed rc owns its source line
            return self._rc_has_block(rc_path)             # (install advises what to add to it)
        if shell == 'bash':
            # bash used to ride the Debian-only `~/.bash_aliases` convention (nothing else sources it —
            # Fedora/EL/Arch/Void/Alpine never loaded bash glue: B3). Now it's a ~/.bashrc block like
            # zsh's; our old link goes (anything it absorbed stays in conf.d, which the block sources)
            self._retire_bash_aliases_link()
            self._ensure_bash_profile()
        block = self._rc_block(shell)
        existing = _read_rc(rc_path) if rc_path.exists() else ''
        if _RC_BEGIN in existing:                           # replace our block in place (idempotent)
            # `block` is generated shell content (inlined snippets) — as a re.sub REPLACEMENT string a
            # `\1`/`\g<>`/backslash in it would be reinterpreted (mangling \t, raising on \1). Pass a
            # function so the replacement is taken literally.
            new = re.sub(re.escape(_RC_BEGIN) + r'.*?' + re.escape(_RC_END) + r'\n?',
                         lambda _m: block, existing, flags=re.DOTALL)
        else:
            sep = '' if (not existing or existing.endswith('\n')) else '\n'
            new = f'{existing}{sep}{block}'
        rc_path.parent.mkdir(parents=True, exist_ok=True)
        _write_rc(rc_path, new)
        return True

    def _record_launcher(self):
        '''Write the clone's launcher path to `<state>/launcher`, which every 00-configsys prelude
        reads (after $CONFIGSYS_LAUNCHER, before the `$HOME/<src>/configsys` guess) to find configsys
        when it isn't on PATH — so `configsys`/`cfs` work wherever the clone actually lives. Only when
        the repo has a configsys.sh; rewritten only on change; best-effort.'''
        p = self.paths
        state = getattr(p, 'state_dir', None) if p is not None else None
        repo = getattr(p, 'repo', None) if p is not None else None
        if state is None or repo is None:
            return
        launcher = Path(repo) / 'configsys.sh'
        if not launcher.is_file():
            return
        rec = Path(state) / 'launcher'
        text = f'{launcher.resolve()}\n'
        try:
            if not rec.is_file() or rec.read_text() != text:
                rec.parent.mkdir(parents=True, exist_ok=True)
                rec.write_text(text)
        except OSError:
            pass

    def _retire_bash_aliases_link(self):
        '''Drop OUR ~/.bash_aliases link — one to the loader's store copy, or into a glue root configsys
        owns. A real file stays, and so does anyone else's link (stow/chezmoi), whatever it is named.'''
        dst = self._home() / '.bash_aliases'
        store = self._store_path(_BASH_ALIASES_SRC)
        try:
            if dst.is_symlink() and ((store is not None and os.path.realpath(dst) == os.path.realpath(store))
                                     or self._link_into_owned(dst)):
                dst.unlink()
        except OSError:
            pass

    def _ensure_bash_profile(self):
        '''Where no login profile exists at all, write ~/.bash_profile sourcing ~/.bashrc.'''
        if any(self._expand(p).exists() or self._expand(p).is_symlink() for p in _BASH_PROFILES):
            return
        prof = self._expand(_BASH_PROFILES[0])
        prof.write_text(f'{_RC_BEGIN}\n{_BASH_PROFILE_BODY}\n{_RC_END}\n')

    def _remove_shell_loader(self, shell):
        '''Remove our hookup for a shell: its rc marker block (bash/zsh/elvish/nushell; bash's old
        ~/.bash_aliases link goes too). Fish has no rc block. Leaves the conf.d dir + any snippet
        content alone.'''
        if getattr(self.runner, 'pretend', False):         # --pretend: write nothing
            return
        if shell == 'bash':
            self._retire_bash_aliases_link()               # drop OUR old link, if one is left
        rc_rel = _SHELL_RC.get(shell)
        if rc_rel is None:
            return
        rc_path = self._expand(rc_rel)
        if not rc_path.exists():
            return
        if rc_path.is_symlink():
            # a captured/managed rc (zsh-dotfiles links ~/.zshrc into your store or primary): its
            # loader block is part of YOUR portable config, shared with your other machines — never
            # edited through the link (install doesn't add it there either; dotfiles-glue-17)
            return
        text = _read_rc(rc_path)
        if _RC_BEGIN not in text:
            return
        new = re.sub(r'\n?' + re.escape(_RC_BEGIN) + r'.*?' + re.escape(_RC_END) + r'\n?',
                     '\n', text, flags=re.DOTALL)
        _write_rc(rc_path, new)

    def _loader_ok(self, shell):
        '''True if `shell`'s loader is fully hooked: dir present, plus the rc block for the rc-driven
        shells (bash/zsh/elvish/nushell) where those apply (fish needs only the dir).'''
        if not self._confd(shell).is_dir():
            return False
        rc_rel = _SHELL_RC.get(shell)
        if rc_rel is not None and not self._rc_has_block(self._expand(rc_rel)):
            return False
        if shell in _INLINE_SHELLS and rc_rel is not None \
                and not self._inline_current(shell, self._expand(rc_rel)):
            return False                                   # a stale snapshot: re-activate refreshes it
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
        for name, src, dst in specs:
            ref = self._deployed(dst, src, rc)
            tgt = self._expand(dst)
            if not (ref.exists()
                    and os.path.realpath(str(tgt)) == os.path.realpath(str(ref))):
                return None
        return 'linked'

    def spec_states(self, rc):
        '''[SpecState] for status views (name, target display path, state, src_root, src_rel, here,
        kind — always 'glue'). A loader component yields one row per hooked shell (loader-on/off).'''
        out = []
        for shell in self._loader_shells(rc):
            state = 'loader-on' if self._loader_ok(shell) else 'loader-off'
            out.append(_linked.SpecState(f'{shell} loader', self.display_path(self._confd(shell)), state,
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
            out.append(_linked.SpecState(name, self.display_path(tgt), state, src_root, rel, here, 'glue'))
        return out

    def warnings(self, rc):
        return []                                          # glue is shipped content — nothing to adopt

    def get_latest(self, rc):
        return None

    # -- mutate -----------------------------------------------------------

    @staticmethod
    def _shell_of(spec_name):
        '''The shell a snippet spec belongs to (its `glue@<shell>` suffix), or None.'''
        return spec_name.rsplit('@', 1)[1] if '@' in spec_name else None

    def install(self, rc, only_shells=None, *, hookup=True):
        '''Activate `rc`'s glue. `only_shells` (a set/list of shell names) scopes the op to just those
        shells — the TUI passes it so activating a snippet in one shell group doesn't light up the
        component's OTHER shells (each per-shell row is independently activatable). None = all shells
        (the CLI install path). `hookup=False` links the snippets but leaves each shell's loader to the
        caller — a bulk activate hooks each shell up ONCE at the end (`deploy_user_glue`) instead of
        regenerating an inline block, and re-running every generator, per snippet.'''
        # A glue snippet lands in the user's conf.d and is sourced by every interactive shell (and a
        # #!cs-eval snippet runs a command at activation) — so it is code. Refuse to materialize an
        # untrusted plugin's glue; the user must `plugin trust` it first.
        if not self.command_trusted(rc):
            return self.untrusted_command_result(rc)
        loaders = self._loader_shells(rc)
        if only_shells is not None:
            loaders = [l for l in loaders if l in only_shells]
        if loaders:                                        # a loader component (loader: zsh | all)
            hooked, not_hooked, warns = [], [], []
            for shell in loaders:
                self.hookup_warnings = []
                (hooked if self._ensure_shell_loader(shell, rc) else not_hooked).append(shell)
                warns += self.hookup_warnings                      # user glue left unlinked (untrusted)
            if not_hooked:
                # your rc is a captured/managed link: its loader line is part of YOUR config, so say
                # exactly what to add instead of claiming success (dotfiles-glue-18)
                lines = [f'{self.display_path(self._expand(_SHELL_RC[s])) if s in _SHELL_RC else s}: it is a link to your captured config — add the '
                         f'conf.d loader to it yourself:\n{self._rc_block(s)}' for s in not_hooked]
                head = (f'glue: conf.d loader hooked up ({", ".join(hooked)}); ' if hooked else 'glue: ')
                return Result(head + 'not hooked: ' + ', '.join(not_hooked), 1,
                              stderr='\n'.join(lines), advisory=True)
            return Result(f'glue: conf.d loader hooked up ({", ".join(hooked)})', 0, stdout='\n'.join(warns))
        specs = self._specs(rc)
        if only_shells is not None:
            specs = [s for s in specs if self._shell_of(s[0]) in only_shells]
        if not specs:
            return Result(f'glue: {rc.comp} has no snippet for any installed shell', 0, advisory=True)
        # Deploy each snippet into the machine-local store MIRROR (<store>/<shell>/conf.d/), so a link
        # never references the repo. `refresh=True`
        # re-caches a store copy that has drifted from its (updated) authoritative source.
        pairs, shells, updated = [], set(), 0
        trust = {}
        for name, src, dst in specs:
            srcpath, _tier, _root = self._resolve(src, rc)
            # the snippet that resolved may not be the defining layer's (your primary's override of a
            # repo snippet): the file that goes live must be trusted too, not just rc.source
            if not self._source_trusted(srcpath, trust):
                return Result.fail(f'{rc.comp}: refusing to activate {self.display_path(srcpath)} — '
                                   f'{self._untrusted_why(srcpath)}', category='untrusted-plugin')
            store = self._glue_store(dst) or srcpath
            if store != srcpath and store.is_file() and srcpath.is_file():   # drift check vs source
                try:
                    if store.read_bytes() != srcpath.read_bytes():
                        updated += 1
                except OSError:
                    pass
            self._materialize_to(srcpath, store, executable=True, refresh=True)
            sh = self._shell_of(name)
            if sh:
                shells.add(sh)
            pairs.append((srcpath, src, store, self._expand(dst)))
        pretend = bool(getattr(self.runner, 'pretend', False))
        notes = []
        for srcpath, src, link_src, tgt in pairs:
            # (under --pretend the store copy wasn't made: its authoritative source stands in)
            if not (link_src.exists() or (pretend and srcpath.exists())):
                notes.append(f'{rc.comp} not populated ({src} absent)')
                continue
            # a conf.d dir can be communal (fish): a pre-existing real file — or another tool's link —
            # goes to a FREE <name>.pre-configsys[.N], never clobbered (A15); our own link is re-pointed
            res = _linked.link(self.runner, link_src, tgt, ours=lambda d: self._link_into_owned(d, rc))
            if not res.ok:
                return res
            if res.stdout:
                notes.append(res.stdout)
        # Ensure the conf.d LOADER is wired for each shell this snippet deploys to, so it actually
        # sources — checked on every install AND update (upgrade == install). The snippet's own
        # `requires: shell-glue` covers the CLI pipeline, but a direct activate (TUI) bypasses it.
        warns = []
        for shell in (shells if hookup else ()):
            self.inline_warnings, self.hookup_warnings = [], []
            self._ensure_shell_loader(shell, rc)
            warns += getattr(self, 'hookup_warnings', []) + getattr(self, 'inline_warnings', [])
        msg = f'activated {rc.comp}'
        if updated:
            msg += f' ({updated} snippet(s) refreshed from source)'
        if notes or warns:                                  # moved aside / unpopulated / left out
            msg += '\n' + '\n'.join(notes + warns)
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
        kept = []
        for name, _src, dst in specs:
            tgt = self._expand(dst)
            # only our own link goes (another tool's link at that name is left), and a file we had
            # moved aside comes back into the gap
            outcome, detail = _linked.unlink(self.runner, tgt, ours=lambda d: self._link_into_owned(d, rc))
            if outcome == 'error':
                return Result(f'glue uninstall {rc.comp}', 1, stderr=detail)
            if outcome == 'kept':
                kept.append(self.display_path(tgt))
        res = Result(f'glue uninstall {rc.comp}', 0,
                     stdout=('left in place (not configsys\'s link): ' + ', '.join(kept)) if kept else '')
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


# public spellings of what the CLI asks the glue driver (F4: app.py reached the private ones)
Glue.installed_shells = Glue._installed_shells
Glue.user_glue_roots = Glue._user_glue_roots
Glue.load_overrides = Glue._load_overrides
Glue.specs = Glue._specs
Glue.dest_glue_root = Glue._dest_glue_root
