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

    def installed_index(self):
        '''{package: version} from ONE `opam list` — the base batch_index enumerates once instead of
        a call per package during inspect. --safe never mutates / never errors on an uninitialized
        opam (it just yields empty output -> nothing installed).'''
        r = self.runner.run('opam list --installed --short --columns=name,version --safe')
        if not r.ok:
            return None
        idx = {}
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                idx[parts[0]] = parts[1]
        return idx

    def get_version(self, rc):
        ver, hit = self._batched_version(rc)          # answer from the one `opam list` when batched
        if hit:
            return ver
        # --safe never mutates and never errors on an uninitialized opam (which otherwise
        # exits 50 demanding `opam init`): it just yields empty output → not installed.
        r = self.runner.run(
            f'opam list --installed --short --columns=version --safe {shlex.quote(self._pkg(rc))}')
        if not r.ok or not r.stdout:
            return None
        v = r.stdout.strip().splitlines()
        return v[0].strip() if v and v[0].strip() else None

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

    def location(self, rc):
        return '~/.opam'
