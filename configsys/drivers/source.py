'''source.py — the source driver: build a component from a git checkout.

A first-class, DECLARATIVE build-from-source medium for the simple majority (`./configure &&
make && make install` into a prefix). The component declares its build as route data — no
per-app Python — so `via: source` is just another binding a base component, a user layer, or a
"gentoo-ish" plugin can add alongside native/flatpak (the additive merge makes that cheap).
Genuinely gnarly builds (GPU-SDK resolution, EULAs, vendor bootstrap scripts) still warrant a
bespoke plugin driver; this is for the ones that don't.

Route fields (on the binding):
  repo:         (required) git URL to clone
  build:        (required) shell command(s) — a string or a list run in sequence — executed IN
                the checked-out tree, with $PREFIX / $SRC / $VERSION / $ARCH substituted
                (e.g. `./configure --prefix=$PREFIX && make -j && make install`)
  version:      (optional) a discovery spec (github/…) or literal; "latest" = that version
  ref:          (optional) explicit git ref (tag/branch/commit); overrides version→tag
  tag-prefix:   (optional) prepended to the version to form the tag (e.g. `v`)
  installDir:   (optional) where the source tree is cloned — scope-honoring, bare-relative
                resolves under HOME (user) / /opt (system); default `src/<comp>`. This is $SRC.
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
        return self.scoped_dir(rc.fields.get('installDir') or f'src/{rc.comp}', rc)

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
        repo = rc.fields.get('repo')
        steps = self._build_steps(rc)
        if not repo:
            return Result.fail(f'{rc.comp}: source binding has no `repo:` to clone')
        if not steps:
            return Result.fail(f'{rc.comp}: source binding has no `build:` command')
        version = version if version is not None else (self.resolve_version(rc) or '')
        src = self._src_dir(rc)
        prefix = self._prefix(rc)
        ref = self._ref(rc, version)
        build = ' && '.join(self._sub(s, version, src, prefix) for s in steps)

        srcq = shlex.quote(str(src))
        cmd = (f'mkdir -p {shlex.quote(str(src.parent))} {shlex.quote(str(prefix))} && '
               f'{{ [ -d {srcq}/.git ] || git clone {shlex.quote(repo)} {srcq}; }} && '
               f'git -C {srcq} fetch --tags --force && '
               f'git -C {srcq} checkout {shlex.quote(ref)} && '
               f'( cd {srcq} && {build} ) && '
               f'printf %s {shlex.quote(version or ref)} > {shlex.quote(str(self._marker(rc)))}')
        return self.runner.run(cmd, capture=False)

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
