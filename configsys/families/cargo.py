'''cargo.py — the \\cargo family: Rust binary crates via `cargo install`.

User-space (installs to ~/.cargo/bin, no sudo). Version state comes from
`cargo install --list`; there's no native version lock, so lock intent lives in
the ledger. The `cargo` tool itself is the family `!depends` (-> apt\\cargo).

get_latest is deferred (crates.io lookup would be a network call per inspect);
`cargo install` fetches the latest at install time.
'''

import re
import shlex

from ..component import Family
from ..runner import Result

# `cargo install --list` lines look like: "tree-sitter-cli v0.20.8:"
_LIST_RE = re.compile(r'^(\S+)\s+v?([^\s:]+):')


class Cargo(Family):
    name = 'cargo'
    privileged = False

    @staticmethod
    def _crate(rc):
        return rc.name  # route `name` field is the crate name

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        r = self.runner.run('cargo install --list')
        if not r.ok:
            return None
        crate = self._crate(rc)
        for line in r.stdout.splitlines():
            m = _LIST_RE.match(line)
            if m and m.group(1) == crate:
                return m.group(2)
        return None

    def get_latest(self, rc):
        return None  # deferred; `cargo install` resolves latest at install time

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        return self.runner.run(f'cargo install {shlex.quote(self._crate(rc))}',
                               capture=False)

    def uninstall(self, rc):
        return self.runner.run(f'cargo uninstall {shlex.quote(self._crate(rc))}',
                               capture=False)

    def upgrade(self, rc):
        # --force reinstalls at the latest version
        return self.runner.run(f'cargo install --force {shlex.quote(self._crate(rc))}',
                               capture=False)

    def set_version(self, rc, version):
        return self.runner.run(
            f'cargo install --force --version {shlex.quote(version)} '
            f'{shlex.quote(self._crate(rc))}', capture=False)

    def lock(self, rc):
        return Result('(cargo lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(cargo unlock recorded in ledger)', 0)

    def location(self, rc):
        return '~/.cargo/bin'
