'''opam.py — the opam driver: OCaml packages via `opam install`.

User-space: opam keeps everything under ~/.opam (per-user switches), no sudo. Version
state comes from `opam list --installed --short --columns=version <pkg>`; no native
version lock, so lock intent lives in the ledger.

The opam tool is the driver `requires: opam`, satisfied by the `opam` component.
get_latest is deferred to a `version:` spec (no network per inspect). Command syntax
confirmed against opam 2.1.5.
'''

import shlex

from ..driver import Driver
from ..runner import Result


class Opam(Driver):
    name = 'opam'
    privileged = False

    @staticmethod
    def _pkg(rc):
        return rc.name  # route `name` field is the opam package

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        # --safe never mutates and never errors on an uninitialized opam (which otherwise
        # exits 50 demanding `opam init`): it just yields empty output → not installed.
        r = self.runner.run(
            f'opam list --installed --short --columns=version --safe {shlex.quote(self._pkg(rc))}')
        if not r.ok or not r.stdout:
            return None
        v = r.stdout.strip().splitlines()
        return v[0].strip() if v and v[0].strip() else None

    def get_latest(self, rc):
        return self.resolve_version(rc)

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        # opam refuses every package op until it's initialised; `opam init` is idempotent (a
        # fast no-op once done, a one-time compiler-switch setup the first time).
        return self.runner.run(
            f'opam init --no-setup --yes && opam install -y {shlex.quote(self._pkg(rc))}',
            capture=False)

    def uninstall(self, rc):
        return self.runner.run(f'opam remove -y {shlex.quote(self._pkg(rc))}', capture=False)

    def upgrade(self, rc):
        return self.runner.run(f'opam upgrade -y {shlex.quote(self._pkg(rc))}', capture=False)

    def set_version(self, rc, version):
        # opam pins a version with the `pkg.version` form
        spec = f'{self._pkg(rc)}.{version}'
        return self.runner.run(f'opam install -y {shlex.quote(spec)}', capture=False)

    def lock(self, rc):
        return Result('(opam lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(opam unlock recorded in ledger)', 0)

    def location(self, rc):
        return '~/.opam'
