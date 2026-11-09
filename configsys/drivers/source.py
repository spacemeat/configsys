'''source.py — the source driver: build a component from a git checkout.

A first-class, DECLARATIVE build-from-source medium for the simple majority (`./configure &&
make && make install` into a prefix). The component declares its build as route data — no
per-app Python — so `via: source` is just another binding a base component, a user layer, or a
"gentoo-ish" plugin can add alongside native/flatpak (the additive merge makes that cheap).
Genuinely gnarly builds (GPU-SDK resolution, EULAs, vendor bootstrap scripts) still warrant a
bespoke plugin driver; this is for the ones that don't.

Acquisition is either git or an archive; `build:` is what makes this the source (not tarball)
driver — tarball = acquire an archive and run it as-is (binary); source = acquire (git OR
archive) and build it. The download/extract step is the same code both drivers share.

Route fields (on the binding):
  build:        (required) shell command(s) — a string or a list run in sequence — executed IN
                the tree, with $PREFIX / $SRC / $VERSION / $ARCH / $SUDO substituted
                (e.g. `./configure --prefix=$PREFIX && make -j && $SUDO make install`). $SUDO is
                `sudo` at system scope and empty at user scope — a system-prefix recipe must use it
  repo:         git URL to clone  (git acquisition; `requires: git`), OR
  url: / version:+asset:          a source archive to download  (`requires: curl`) — reuses the
                same url template / github discovery as the tarball driver
  strip:        (archive only, tar) leading path components to drop; default 1 (source tarballs
                wrap their contents in a `foo-<version>/` dir). Set 0 to disable.
  version:      (optional) a discovery spec (github/…) or literal; "latest" = that version
  ref:          (optional) explicit git ref (tag/branch/commit); overrides version→tag
  tag-prefix:   (optional) prepended to the version to form the tag (e.g. `v`)
  installDir:   (optional) where the source tree lands (cloned or extracted); bare-relative resolves
                under the USER base at either scope — the tree is a build cache you own, never root's
                (only $PREFIX follows scope); default `src/<comp>` ($SRC).
  prefix:       (optional) install prefix ($PREFIX); default ~/.local (user) or /usr/local
                (system). A bare-relative path resolves like installDir.
  uninstall-cmd:(optional) run in the tree before the source is removed (e.g. `make uninstall`);
                absent => the tree is removed but files under the prefix may remain (warned).
  location:     (optional) display path override.

Userland always: the build runs as you (building as root is wrong). At `scope: system` only the
install step gets root, through the recipe's `$SUDO`; a recipe without it is refused at system scope
up front rather than failing at `make install`. The built version is recorded in a marker file in the
source tree, so inspection is stateless (the tarball driver's model). No native lock — intent lives
in the ledger.

UPGRADE: a branch recipe (no `version:`, or `ref: <branch>`) follows the REMOTE branch — after the
fetch the tree is reset to `origin/<branch>` (the remote's default branch for HEAD), so an upgrade
builds the new upstream commit; a tag/sha ref is checked out as-is. A changed `repo:` re-points a
configsys-made tree's `origin`. An adopted checkout is fast-forwarded only (`merge --ff-only`).

REBUILD SEMANTICS: install/upgrade REBUILD unconditionally from a PRISTINE tree — after fetch we
force-checkout the ref (`git checkout -f`, resetting tracked files a build step may patch) and
`git clean -xfd` (removing git-ignored build artifacts, e.g. a cached CMakeCache.txt) so a recipe
change or a failed partial build can't be masked by stale state. There is no "already built, skip":
`configsys install <comp>` re-runs the whole build (use `install --no-deps <comp>` to rebuild just
this component without re-running its dependency installs). The version marker is the only thing
preserved across the clean, so a failed rebuild still reads as installed (the artifacts live under
$PREFIX, which the clean never touches). An ARCHIVE rebuild extracts into a fresh sibling stage and
swaps it in (carrying only configsys's markers), so files deleted upstream or a stale CMakeCache.txt
never survive; an adopted tree is extracted over in place (it is yours).
'''

import shlex

from ..driver import Driver
from ..runner import Result

MARKER_PREFIX = Driver.MARKER_PREFIX


class Source(Driver):
    name = 'source'
    privileged = False
    default_scope = 'user'
    honors_scope = True

    # -- locations --------------------------------------------------------

    def _src_dir(self, rc):
        raw = rc.fields.get('installDir') or f'$CONFIGSYS_SRC_DIR/{rc.comp}'
        if self.location_override(rc):
            return self.location_override(rc)
        if self.paths is not None:                 # the tree is user space at EITHER scope (B14)
            return self.paths.install_dir(raw, 'user')
        return self.scoped_dir(raw, rc)

    def _prefix(self, rc):
        p = rc.fields.get('prefix')
        if p:
            return self.scoped_dir(p, rc)
        base = '/usr/local' if self._scope(rc) == 'system' else '~/.local'
        return self.scoped_dir(base, rc)

    def _own_marker(self, rc, kind):
        '''`<src>/.configsys-<comp>.<kind>` — `cloned` (configsys created the tree) or `adopted`.'''
        return self.marker_path(self._src_dir(rc), rc, kind)

    def _marker(self, rc):
        return self.marker_path(self._src_dir(rc), rc)

    def _ref(self, rc, version):
        '''The git ref to check out: an explicit `ref:`, else `tag-prefix`+version, else HEAD.'''
        if rc.fields.get('ref'):
            return str(rc.fields['ref'])
        if version:
            return f"{rc.fields.get('tag-prefix', '')}{version}"
        return 'HEAD'

    def _sub(self, text, version, src, prefix, rc=None):
        sudo = 'sudo' if rc is not None and self._scope(rc) == 'system' else ''
        # $ARCH is the binding's `cpu-names:` token, as in its download url (drivers-lang-31)
        arch = self.arch_token(rc) if rc is not None else self.arch()
        return (str(text).replace('$PREFIX', str(prefix)).replace('$SRC', str(src))
                .replace('$VERSION', version or '').replace('$ARCH', arch)
                .replace('$SUDO', sudo))

    @staticmethod
    def _build_steps(rc):
        b = rc.fields.get('build')
        return b if isinstance(b, list) else ([b] if b else [])

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        return self.read_marker(self._marker(rc))     # empty = present, version unrecorded

    def get_installed(self, rc):
        return self._installed_across_scopes(rc)

    # -- mutate -----------------------------------------------------------

    def install(self, rc, version=None):
        if not self.command_trusted(rc):               # untrusted plugin: refuse to run its build
            return self.untrusted_command_result(rc)
        steps = self._build_steps(rc)
        if not steps:
            return Result.fail(f'{rc.comp}: source binding has no `build:` command')
        if self._scope(rc) == 'system' and not any('$SUDO' in str(s) or 'sudo ' in str(s) for s in steps):
            return Result('', 1, advisory=True, stderr=(
                f'{rc.comp}: a `scope: system` build installs into {self._prefix(rc)}, which needs root, '
                f'but its recipe has no `$SUDO` on the install step (e.g. `$SUDO make install`) — add '
                f'it in your layer, or install {rc.comp} at user scope'))
        explicit = version is not None
        version = version if explicit else (self.resolve_version(rc) or '')
        src = self._src_dir(rc)
        prefix = self._prefix(rc)
        srcq = shlex.quote(str(src))

        # OWNERSHIP (review-2026-11-2 A9): a tree configsys didn't create is never cleaned or deleted.
        # `.configsys-<comp>.cloned` = configsys made it (clone / archive extract); `.adopted` = you let
        # configsys build in your own checkout (`install --adopt`: fetch + checkout only, never a
        # clean or a forced reset, never removed); `.version` alone = an install from before these
        # markers. A dir with none of them is refused, naming --adopt.
        why = self.unsafe_dir_reason(src)
        if why:
            return Result.fail(f'{rc.comp}: refusing to build in {src} — {why}')
        cloned, adopted = self._own_marker(rc, 'cloned'), self._own_marker(rc, 'adopted')
        clq, adq, vmq = (shlex.quote(str(cloned)), shlex.quote(str(adopted)),
                         shlex.quote(str(self._marker(rc))))
        force = bool(getattr(self.paths, 'install_force', False))
        adopt = bool(getattr(self.paths, 'source_adopt', False))
        claim = (f'if [ -e {srcq} ] && [ ! -e {vmq} ] && [ ! -e {clq} ] && [ ! -e {adq} ]; then '
                 + (f'touch {adq}; ' if adopt else
                    f'echo "configsys: {src} exists and configsys didn\'t create it — '
                    f'\\`configsys install {rc.comp} --adopt\\` builds there (fetch + checkout only; '
                    f'your files are never cleaned or deleted), or move it aside" >&2; exit 3; ')
                 + 'fi && ')

        mine_q = shlex.quote(f'{MARKER_PREFIX}*')
        repo = rc.fields.get('repo')
        if repo:                                    # git acquisition: clone-or-fetch, checkout ref
            ref = self._ref(rc, version)
            # After checkout, scrub the tree PRISTINE (`git clean -xfd`): a reused checkout keeps
            # git-ignored build artifacts — an out-of-source `build/` with a cached CMakeCache.txt,
            # autotools' generated files — so a rebuild reuses the STALE configuration and a recipe
            # change (or a failed partial build) never takes effect. Exclude our version marker so a
            # failed rebuild doesn't wrongly read as uninstalled (the artifacts install into $PREFIX,
            # which the clean never touches). See docs/done/driver-resilience-plan.md (transactional builds).
            # An ADOPTED checkout is yours: a plain checkout (it fails rather than overwrite your
            # edits), no clean. A configsys-made tree with local changes (you edited config.h, a
            # failed build patched a file) is refused unless --force, which discards them.
            refq = shlex.quote(ref)
            repoq = shlex.quote(repo)
            mine = shlex.quote(f'{MARKER_PREFIX}*')
            dirty = (f'[ -z "$(git -C {srcq} status --porcelain --untracked-files=normal -- . '
                     f'\":(exclude){MARKER_PREFIX}*\")" ]')
            # B14: a branch follows the REMOTE. B = the branch to track: the remote's default branch
            # for HEAD (configsys-made) or your current branch (adopted), else the `ref:` itself when
            # origin has such a branch; empty = a tag/sha, checked out as-is.
            if ref == 'HEAD':
                pick_mine = (f'B="$(git -C {srcq} symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null '
                             f'|| {{ git -C {srcq} remote set-head origin -a >/dev/null 2>&1 && '
                             f'git -C {srcq} symbolic-ref --short refs/remotes/origin/HEAD; }})"; B="${{B#origin/}}"; ')
                pick_adopted = f'B="$(git -C {srcq} symbolic-ref --short HEAD 2>/dev/null)"; '
            else:
                pick_mine = pick_adopted = f'B={refq}; '
            on_remote = f'[ -n "$B" ] && git -C {srcq} show-ref --verify --quiet "refs/remotes/origin/$B"'
            pristine = (f'{pick_mine}if {on_remote}; then git -C {srcq} checkout -f -B "$B" "origin/$B"; '
                        f'else git -C {srcq} checkout -f {refq}; fi && '   # -f resets tracked files (a build may patch one)
                        f'git -C {srcq} clean -xfd -e {mine}')
            adopted_co = (f'{pick_adopted}if {on_remote}; then git -C {srcq} checkout "$B" && '
                          f'git -C {srcq} merge --ff-only "origin/$B"; '
                          f'elif [ {refq} != HEAD ]; then git -C {srcq} checkout {refq}; fi')
            guard = ('' if force else
                     f'{{ {dirty} || {{ echo "configsys: {src} has local changes — commit or stash '
                     f'them, or \\`install --force\\` to discard them" >&2; exit 4; }}; }} && ')
            acquire = (f'{claim}{{ [ -d {srcq}/.git ] || {{ git clone {repoq} {srcq} && '
                       f'touch {clq}; }}; }} && '
                       # a changed `repo:` re-points a tree configsys made (never your adopted one)
                       f'{{ [ -e {adq} ] || git -C {srcq} remote set-url origin {repoq}; }} && '
                       f'git -C {srcq} fetch --tags --force && '
                       f'if [ -e {adq} ]; then {adopted_co}; '
                       f'else {guard}{pristine}; fi')
            stamp = version or ref
        else:                                       # archive acquisition: download + extract
            # the version of the archive actually fetched (an asset glob's release may differ from
            # the feed-discovered one); an explicit set_version target is kept as given
            version, url = self.download_target(rc, version if explicit else None)
            if not url:
                spec = self._disco_spec(rc)
                if rc.fields.get('url') or (isinstance(spec, dict) and spec.get('asset')):
                    return Result.fail(self.download_failure(rc, version))   # declared, unresolved
                return Result.fail(f'{rc.comp}: source binding has neither a `repo:` to clone nor '
                                   f'a `url:`/`version:` archive to download')
            # B14: a configsys-made tree is rebuilt from a FRESH extract — into a sibling stage, our
            # markers carried over, then swapped in — so files deleted upstream and a stale
            # CMakeCache.txt don't survive. An adopted tree is yours: extracted over in place.
            stage = shlex.quote(str(src) + MARKER_PREFIX + 'stage')
            fetch = lambda dest: self._fetch_and_extract(url, dest, rc.fields.get('archive'),  # noqa: E731
                                                         rc.fields.get('strip', 1), rc=rc)
            acquire = (f'{claim}'
                       f'if [ -e {adq} ]; then {fetch(src)}; else '
                       f'rm -rf {stage} && {fetch(str(src) + MARKER_PREFIX + "stage")} && '
                       f'{{ [ ! -d {srcq} ] || find {srcq} -maxdepth 1 -name {mine_q} '
                       f'-exec mv -f {{}} {stage}/ \\; ; }} && touch {stage}/{shlex.quote(cloned.name)} && '
                       f'rm -rf {srcq} && mv {stage} {srcq}; fi')
            stamp = version or 'source'

        build = ' && '.join(self._sub(s, version, src, prefix, rc) for s in steps)
        path = self._build_path(rc, version, src, prefix)
        mk_prefix = (f'{{ [ -d {shlex.quote(str(prefix))} ] || sudo mkdir -p {shlex.quote(str(prefix))}; }}'
                     if self._scope(rc) == 'system' else f'mkdir -p {shlex.quote(str(prefix))}')
        cmd = (f'mkdir -p {shlex.quote(str(src.parent))} && {mk_prefix} && '
               f'{acquire} && '
               f'( cd {srcq} && export PATH="{path}:$PATH" && {build} ) && '
               f'printf %s {shlex.quote(stamp)} > {shlex.quote(str(self._marker(rc)))}')
        return self.runner.run(cmd, capture=False)

    # The managed toolchains' bin dirs (Driver.toolchain_bindirs: the Go tarball under
    # $CONFIGSYS_SDK_DIR/go at either scope, as `dirs:`/env lay it out, `go install` tools in ~/go/bin,
    # rustup's ~/.cargo/bin) are prepended to PATH for the build so a NON-native toolchain a recipe
    # `requires:` is found. A native toolchain on the system PATH still works (these just take
    # precedence when present; a missing dir is harmlessly ignored by PATH lookup). This is what lets
    # a floor-pinned toolchain (rust->rustup, go->tarball) actually build, since the build runs in a
    # fresh non-interactive shell that hasn't sourced bash.d. A recipe adds more via `build-path:`.

    def _build_path(self, rc, version, src, prefix):
        extra = rc.fields.get('build-path')
        extra = extra if isinstance(extra, list) else ([extra] if extra else [])
        dirs = self.toolchain_bindirs() + [self._sub(d, version, src, prefix) for d in extra]
        return ':'.join(dirs)   # a `build-path:` $HOME is left literal for the build shell; route data trusted

    def upgrade(self, rc):
        # idempotent: re-resolve latest, fetch, checkout the new ref, rebuild in place
        return self.install(rc)

    def set_version(self, rc, version):
        return self.install(rc, version=version)

    def uninstall(self, rc):
        if not self.command_trusted(rc):               # untrusted plugin: refuse its uninstall-cmd
            return self.untrusted_command_result(rc)
        src = self._src_dir(rc)
        srcq = shlex.quote(str(src))
        unc = rc.fields.get('uninstall-cmd')
        pre = (f'( cd {srcq} && {self._sub(unc, "", src, self._prefix(rc), rc)} ) && ' if unc else '')
        cloned = shlex.quote(str(self._own_marker(rc, 'cloned')))
        # only touch a tree we manage (our marker present); DELETE it only when configsys created it,
        # it is a safe path, and it holds no local changes — else it stays, and we say so (A9)
        unsafe = self.unsafe_dir_reason(src)
        clean = (f'{{ [ ! -d {srcq}/.git ] || [ -z "$(git -C {srcq} status --porcelain '
                 f'--untracked-files=normal -- . \":(exclude){MARKER_PREFIX}*\")" ]; }}')
        drop = ('false' if unsafe else f'[ -e {cloned} ] && {clean}')
        cmd = (f'if [ -f {shlex.quote(str(self._marker(rc)))} ]; then {pre}'
               f'if {drop}; then rm -rf {srcq}; else rm -f {shlex.quote(str(self._marker(rc)))}; '
               f'echo "configsys: kept {src} (configsys didn\'t create it, or it has local changes)"; '
               f'fi; fi')
        res = self.runner.run(cmd, capture=False)
        if res.ok and not unc:
            return Result(f'⚠ removed "{rc.comp}" (its source tree is deleted only if configsys created '
                          f'it); files it installed under the prefix may remain (no uninstall-cmd in '
                          f'the route).', 0)
        return res

    def location(self, rc):
        return rc.fields.get('location') or self.display_path(self._prefix(rc))
