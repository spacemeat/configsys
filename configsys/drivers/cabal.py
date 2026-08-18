'''cabal.py — the cabal driver: Haskell executables via `cabal install`.

User-space: cabal installs executables into ~/.cabal/bin, no sudo. Installed state comes
from that symlink: `cabal install <pkg>` symlinks ~/.cabal/bin/<exe> -> the versioned
store dir (…/<pkg>-<version>-<hash>/bin/<exe>), so the resolved path carries the version.
(`cabal list --installed` only reports LIBRARY packages in the ghc db, NOT installed
executables — it misses hlint et al.) cabal has no native uninstall for executables, so
removal deletes the binary; and no native version lock, so lock intent lives in the ledger.

The cabal tool is the driver `requires: cabal`, satisfied by the `cabal` component
(which pulls ghc). Command syntax confirmed against cabal-install 3.8.1.
'''

import re
import shlex

from ..driver import Driver
from ..runner import Result

_CABAL_BIN = '~/.cabal/bin'
# Prefer a ghcup toolchain (modern GHC + cabal in ~/.ghcup/bin) over the distro cabal/ghc when it's
# installed: the non-interactive runner shell doesn't source ghcup's env, so a bare `cabal`/`ghc`
# would be the distro's — often too old to build a recent Hackage package (hlint). If ghcup isn't
# installed the dir doesn't exist and PATH falls through to the distro toolchain.
_GHCUP_BIN = '$HOME/.ghcup/bin'


class Cabal(Driver):
    name = 'cabal'
    privileged = False

    def _cabal(self, subcmd, **kw):
        return self.runner.run(f'PATH="{_GHCUP_BIN}:$PATH" cabal {subcmd}', **kw)

    @staticmethod
    def _pkg(rc):
        return rc.name  # route `name` field is the hackage package

    def _exe(self, rc):
        # best-effort: the installed executable usually matches the package name; a route can
        # override with an explicit `exe:` field when it doesn't.
        return rc.fields.get('exe') or self._pkg(rc)

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        # resolve the ~/.cabal/bin/<exe> symlink; the store path it points at carries the version.
        # `readlink -e` requires the whole chain to EXIST (empty for an absent/broken link) — unlike
        # `-f`, which prints the path even when the final component is missing (false "installed").
        r = self.runner.run(f'readlink -e {_CABAL_BIN}/{shlex.quote(self._exe(rc))} 2>/dev/null')
        tgt = (r.stdout or '').strip()
        if not tgt:
            return None                                   # no such binary -> not installed
        m = re.search(rf'/{re.escape(self._pkg(rc))}-([0-9][0-9.]*)-', tgt)
        return m.group(1) if m else 'installed'           # present; version unknown (non-store binary)

    def get_latest(self, rc):
        return self.resolve_version(rc)

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def _ensure_index(self):
        '''cabal's dependency solver needs a package index; a fresh cabal has none, so `cabal install`
        fails with "goals I've had most trouble fulfilling: <pkg>". Populate it once (idempotent —
        skipped when an index is already present, so a batch doesn't re-fetch per package).'''
        r = self.runner.run('ls ~/.cabal/packages/*/*.tar* ~/.cache/cabal/packages/*/*.tar* 2>/dev/null')
        if not (r.ok and r.stdout.strip()):
            self._cabal('update', capture=False)

    def install(self, rc):
        self._ensure_index()
        return self._cabal(
            f'install {shlex.quote(self._pkg(rc))} --overwrite-policy=always', capture=False)

    def uninstall(self, rc):
        # cabal has no `uninstall` for executables — remove the installed binary
        return self.runner.run(f'rm -f {_CABAL_BIN}/{shlex.quote(self._exe(rc))}', capture=False)

    def upgrade(self, rc):
        return self.install(rc)

    def set_version(self, rc, version):
        self._ensure_index()
        spec = f'{self._pkg(rc)}-{version}'
        return self._cabal(
            f'install {shlex.quote(spec)} --overwrite-policy=always', capture=False)

    def lock(self, rc):
        return Result('(cabal lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(cabal unlock recorded in ledger)', 0)

    def location(self, rc):
        return _CABAL_BIN
