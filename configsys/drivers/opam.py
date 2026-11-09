'''opam.py — the opam driver: OCaml packages via `opam install`.

User-space: opam keeps everything under ~/.opam (per-user switches), no sudo. Version
state comes from ONE `opam list --installed --short --columns=name,version --safe` per
batch (unbatched: `--columns=version <pkg>`); no native version lock, so lock intent
lives in the ledger.

The opam tool is the driver `requires: opam`, satisfied by the `opam` component.
get_latest is deferred to a `version:` spec (no network per inspect). Command syntax
confirmed against opam 2.1.5.
'''

import shlex

from ._module import ModuleDriver


class Opam(ModuleDriver):
    name = 'opam'
    TOOL = 'opam'
    # opam refuses every package op until it's initialised; `opam init` is idempotent (a fast no-op
    # once done, a one-time compiler-switch setup the first time). A version is spelled `pkg.version`.
    CMDS = {'install': '{tool} init --no-setup --yes && {tool} install -y {pkg}',
            'uninstall': '{tool} remove -y {pkg}',
            'upgrade': '{tool} upgrade -y {pkg}',
            'set_version': '{tool} install -y {spec}'}
    VERSION_SPEC = '{pkg}.{ver}'
    # ONE `opam list` for the batch. --safe never mutates / never errors on an uninitialized opam
    # (it just yields empty output -> nothing installed).
    LIST_CMD = '{tool} list --installed --short --columns=name,version --safe'
    BIN_DIR = '~/.opam'

    # -- read -------------------------------------------------------------

    def parse_list(self, stdout):
        idx = {}
        for line in stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                idx[parts[0]] = parts[1]
        return idx

    def get_version(self, rc):
        ver, hit = self.batched_version(rc)          # answer from the one `opam list` when batched
        if hit:
            return ver
        # --safe never mutates and never errors on an uninitialized opam (which otherwise
        # exits 50 demanding `opam init`): it just yields empty output → not installed.
        r = self.runner.run(
            f'opam list --installed --short --columns=version --safe {shlex.quote(self.module(rc))}')
        if not r.ok or not r.stdout:
            return None
        v = r.stdout.strip().splitlines()
        return v[0].strip() if v and v[0].strip() else None
