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
                the tree, with $PREFIX / $SRC / $VERSION / $ARCH substituted
                (e.g. `./configure --prefix=$PREFIX && make -j && make install`)
  repo:         git URL to clone  (git acquisition; `requires: git`), OR
  url: / version:+asset:          a source archive to download  (`requires: curl`) — reuses the
                same url template / github discovery as the tarball driver
  strip:        (archive only, tar) leading path components to drop; default 1 (source tarballs
                wrap their contents in a `foo-<version>/` dir). Set 0 to disable.
  version:      (optional) a discovery spec (github/…) or literal; "latest" = that version
  ref:          (optional) explicit git ref (tag/branch/commit); overrides version→tag
  tag-prefix:   (optional) prepended to the version to form the tag (e.g. `v`)
  installDir:   (optional) where the source tree lands (cloned or extracted) — scope-honoring,
                bare-relative resolves under HOME (user) / /opt (system); default `src/<comp>` ($SRC).
  prefix:       (optional) install prefix ($PREFIX); default ~/.local (user) or /usr/local
                (system). A bare-relative path resolves like installDir.
  uninstall-cmd:(optional) run in the tree before the source is removed (e.g. `make uninstall`);
                absent => the tree is removed but files under the prefix may remain (warned).
  location:     (optional) display path override.

Userland by default (no auto-sudo — building as root is wrong; put `sudo` in the build/install
step for a system prefix). The built version is recorded in a marker file in the source tree, so
inspection is stateless (the tarball driver's model). No native lock — intent lives in the ledger.
'''

import shlex

from ..driver import Driver
from ..runner import Result

MARKER_PREFIX = '.configsys-'


class Source(Driver):
    name = 'source'
    privileged = False
    default_scope = 'user'
    honors_scope = True

    # -- locations --------------------------------------------------------

    def _src_dir(self, rc):
        return self.scoped_dir(rc.fields.get('installDir') or f'$CONFIGSYS_SRC_DIR/{rc.comp}', rc)

    def _prefix(self, rc):
        p = rc.fields.get('prefix')
        if p:
            return self.scoped_dir(p, rc)
        base = '/usr/local' if self._scope(rc) == 'system' else '~/.local'
        return self.scoped_dir(base, rc)

    def _marker(self, rc):
        return self._src_dir(rc) / f'{MARKER_PREFIX}{rc.comp}.version'

    def _ref(self, rc, version):
        '''The git ref to check out: an explicit `ref:`, else `tag-prefix`+version, else HEAD.'''
        if rc.fields.get('ref'):
            return str(rc.fields['ref'])
        if version:
            return f"{rc.fields.get('tag-prefix', '')}{version}"
        return 'HEAD'

    def _sub(self, text, version, src, prefix):
        return (str(text).replace('$PREFIX', str(prefix)).replace('$SRC', str(src))
                .replace('$VERSION', version or '').replace('$ARCH', self.arch()))

    @staticmethod
    def _build_steps(rc):
        b = rc.fields.get('build')
        return b if isinstance(b, list) else ([b] if b else [])

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        try:
            v = self._marker(rc).read_text(encoding='utf-8').strip()
        except (FileNotFoundError, NotADirectoryError, OSError):
            return None
        return v or None

    def get_installed(self, rc):
        return self._installed_across_scopes(rc)

    def get_latest(self, rc):
        return self.resolve_version(rc)

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc, version=None):
        steps = self._build_steps(rc)
        if not steps:
            return Result.fail(f'{rc.comp}: source binding has no `build:` command')
        version = version if version is not None else (self.resolve_version(rc) or '')
        src = self._src_dir(rc)
        prefix = self._prefix(rc)
        srcq = shlex.quote(str(src))

        repo = rc.fields.get('repo')
        if repo:                                    # git acquisition: clone-or-fetch, checkout ref
            ref = self._ref(rc, version)
            acquire = (f'{{ [ -d {srcq}/.git ] || git clone {shlex.quote(repo)} {srcq}; }} && '
                       f'git -C {srcq} fetch --tags --force && '
                       f'git -C {srcq} checkout {shlex.quote(ref)}')
            stamp = version or ref
        else:                                       # archive acquisition: download + extract
            url = self.download_url(rc, version)
            if not url:
                return Result.fail(f'{rc.comp}: source binding has neither a `repo:` to clone nor '
                                   f'a `url:`/`version:` archive to download')
            acquire = self._fetch_and_extract(url, src, rc.fields.get('archive'),
                                              rc.fields.get('strip', 1))
            stamp = version or 'source'

        build = ' && '.join(self._sub(s, version, src, prefix) for s in steps)
        path = self._build_path(rc, version, src, prefix)
        cmd = (f'mkdir -p {shlex.quote(str(src.parent))} {shlex.quote(str(prefix))} && '
               f'{acquire} && '
               f'( cd {srcq} && export PATH="{path}:$PATH" && {build} ) && '
               f'printf %s {shlex.quote(stamp)} > {shlex.quote(str(self._marker(rc)))}')
        return self.runner.run(cmd, capture=False)

    # Well-known USERLAND toolchain bin dirs, prepended to PATH for the build so a NON-native
    # toolchain a recipe `requires:` is found — rustup's cargo/rustc in ~/.cargo/bin, `go install`
    # tools in ~/go/bin (GOPATH/bin). A native toolchain on the system PATH still works (these just
    # take precedence when present; a missing dir is harmlessly ignored by PATH lookup). This is
    # what lets a floor-pinned toolchain (e.g. rust->rustup) actually build, since the build runs in
    # a fresh non-interactive shell that hasn't sourced bash.d. A recipe adds more via `build-path:`.
    _TOOLCHAIN_BINDIRS = ('$HOME/.cargo/bin', '$HOME/go/bin')

    def _build_path(self, rc, version, src, prefix):
        extra = rc.fields.get('build-path')
        extra = extra if isinstance(extra, list) else ([extra] if extra else [])
        dirs = list(self._TOOLCHAIN_BINDIRS) + [self._sub(d, version, src, prefix) for d in extra]
        return ':'.join(dirs)   # $HOME left literal so the build shell expands it; route data trusted

    def upgrade(self, rc):
        # idempotent: re-resolve latest, fetch, checkout the new ref, rebuild in place
        return self.install(rc)

    def set_version(self, rc, version):
        return self.install(rc, version=version)

    def uninstall(self, rc):
        src = self._src_dir(rc)
        srcq = shlex.quote(str(src))
        unc = rc.fields.get('uninstall-cmd')
        pre = (f'( cd {srcq} && {self._sub(unc, "", src, self._prefix(rc))} ) && ' if unc else '')
        # only touch a tree we manage (our marker present), mirroring the tarball driver
        cmd = (f'if [ -f {shlex.quote(str(self._marker(rc)))} ]; then '
               f'{pre}rm -rf {srcq}; fi')
        res = self.runner.run(cmd, capture=False)
        if res.ok and not unc:
            return Result(f'⚠ removed the source tree for "{rc.comp}"; files it installed under '
                          f'the prefix may remain (no uninstall-cmd in the route).', 0)
        return res

    def lock(self, rc):
        return Result('(source lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(source unlock recorded in ledger)', 0)

    def location(self, rc):
        return rc.fields.get('location') or self.display_path(self._prefix(rc))
