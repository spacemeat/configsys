'''cabal.py — the cabal driver: Haskell executables via `cabal install`.

User-space: cabal installs executables into ~/.cabal/bin, no sudo. Installed state
comes from `cabal list --installed --simple-output` (`<name> <version>` lines). cabal
has no native uninstall for executables, so removal deletes the binary; and no native
version lock, so lock intent lives in the ledger.

The cabal tool is the driver `requires: cabal`, satisfied by the `cabal` component
(which pulls ghc). Command syntax confirmed against cabal-install 3.8.1.
'''

import shlex

from ..driver import Driver
from ..runner import Result

_CABAL_BIN = '~/.cabal/bin'


class Cabal(Driver):
    name = 'cabal'
    privileged = False

    @staticmethod
    def _pkg(rc):
        return rc.name  # route `name` field is the hackage package

    def _exe(self, rc):
        # best-effort: the installed executable usually matches the package name; a route can
        # override with an explicit `exe:` field when it doesn't.
        return rc.fields.get('exe') or self._pkg(rc)

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        r = self.runner.run(
            f'cabal list --installed --simple-output {shlex.quote(self._pkg(rc))}')
        if not r.ok or not r.stdout:
            return None
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == self._pkg(rc):
                return parts[1]
        return None

    def get_latest(self, rc):
        return self.resolve_version(rc)

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        return self.runner.run(
            f'cabal install {shlex.quote(self._pkg(rc))} --overwrite-policy=always',
            capture=False)

    def uninstall(self, rc):
        # cabal has no `uninstall` for executables — remove the installed binary
        return self.runner.run(f'rm -f {_CABAL_BIN}/{shlex.quote(self._exe(rc))}', capture=False)

    def upgrade(self, rc):
        return self.install(rc)

    def set_version(self, rc, version):
        spec = f'{self._pkg(rc)}-{version}'
        return self.runner.run(
            f'cabal install {shlex.quote(spec)} --overwrite-policy=always', capture=False)

    def lock(self, rc):
        return Result('(cabal lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(cabal unlock recorded in ledger)', 0)

    def location(self, rc):
        return _CABAL_BIN
