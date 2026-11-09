'''cabal.py — the cabal driver: Haskell executables via `cabal install`.

User-space: cabal installs executables into ~/.cabal/bin — or, from cabal-install 3.10 on a box
with no ~/.cabal, the XDG ~/.local/bin — no sudo. Installed state comes from that symlink: `cabal
install <pkg>` symlinks <bin>/<exe> -> the versioned store dir (…/<pkg>-<version>-<hash>/bin/<exe>),
so the resolved path carries the version. In ~/.local/bin (shared with everything else) only a link
into a cabal store counts, and only such a link is ever removed.
(`cabal list --installed` only reports LIBRARY packages in the ghc db, NOT installed
executables — it misses hlint et al.) cabal has no native uninstall for executables, so
removal deletes the binary; and no native version lock, so lock intent lives in the ledger.

The cabal tool is the driver `requires: cabal`, satisfied by the `cabal` component
(which pulls ghc). Command syntax confirmed against cabal-install 3.8.1.
'''

import re
import os
import shlex

from ._module import ModuleDriver

_CABAL_BIN = '~/.cabal/bin'
_XDG_BIN = '~/.local/bin'                 # cabal-install >= 3.10 without ~/.cabal (B14)
_STORE_GLOBS = '*/cabal/store/*|*/.cabal/store/*'
# Prefer a ghcup toolchain (modern GHC + cabal in ~/.ghcup/bin) over the distro cabal/ghc when it's
# installed: the non-interactive runner shell doesn't source ghcup's env, so a bare `cabal`/`ghc`
# would be the distro's — often too old to build a recent Hackage package (hlint). If ghcup isn't
# installed the dir doesn't exist and PATH falls through to the distro toolchain.
_GHCUP_BIN = '$HOME/.ghcup/bin'


class Cabal(ModuleDriver):
    name = 'cabal'
    TOOL = f'PATH="{_GHCUP_BIN}:$PATH" cabal'
    # installing an installed executable again upgrades it; a version is `pkg-version`
    CMDS = {'install': '{tool} install {pkg} --overwrite-policy=always',
            'upgrade': '{tool} install {pkg} --overwrite-policy=always',
            'set_version': '{tool} install {spec} --overwrite-policy=always'}
    VERSION_SPEC = '{pkg}-{ver}'
    BIN_DIR = _CABAL_BIN

    def _exe(self, rc):
        # best-effort: the installed executable usually matches the package name; a route can
        # override with an explicit `exe:` field when it doesn't.
        return os.path.basename(str(rc.fields.get('exe') or self.module(rc)))   # a name, never a path

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        # resolve the ~/.cabal/bin/<exe> symlink; the store path it points at carries the version.
        # `readlink -e` requires the whole chain to EXIST (empty for an absent/broken link) — unlike
        # `-f`, which prints the path even when the final component is missing (false "installed").
        exe = shlex.quote(self._exe(rc))
        r = self.runner.run(f'readlink -e {_CABAL_BIN}/{exe} 2>/dev/null || '
                            f'{{ t="$(readlink -e {_XDG_BIN}/{exe} 2>/dev/null)"; '
                            f'case "$t" in {_STORE_GLOBS}) echo "$t";; esac; }}')
        tgt = (r.stdout or '').strip()
        if not tgt:
            return None                                   # no such binary -> not installed
        m = re.search(rf'/{re.escape(self.module(rc))}-([0-9][0-9.]*)-', tgt)
        return m.group(1) if m else 'installed'           # present; version unknown (non-store binary)

    # -- mutate -----------------------------------------------------------

    def _ensure_index(self):
        '''cabal's dependency solver needs a package index; a fresh cabal has none, so `cabal install`
        fails with "goals I've had most trouble fulfilling: <pkg>". Populate it once (idempotent —
        skipped when an index is already present, so a batch doesn't re-fetch per package).'''
        r = self.runner.run('ls ~/.cabal/packages/*/*.tar* ~/.cache/cabal/packages/*/*.tar* 2>/dev/null')
        if not (r.ok and r.stdout.strip()):
            self.runner.run(f'{self.TOOL} update', capture=False)

    def install(self, rc):
        self._ensure_index()
        return self.run_op('install', rc)

    def uninstall(self, rc):
        # cabal has no `uninstall` for executables — remove the installed binary (in ~/.local/bin only
        # a symlink into a cabal store: never a same-named binary something else put there)
        exe = shlex.quote(self._exe(rc))
        return self.runner.run(f'rm -f {_CABAL_BIN}/{exe}; f={_XDG_BIN}/{exe}; '
                               f'if [ -L "$f" ]; then case "$(readlink "$f")" in {_STORE_GLOBS}) '
                               f'rm -f "$f";; esac; fi', capture=False)

    def upgrade(self, rc):
        return self.install(rc)

    def set_version(self, rc, version):
        self._ensure_index()
        return self.run_op('set_version', rc, version)
