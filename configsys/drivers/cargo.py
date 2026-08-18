'''cargo.py — the cargo driver: Rust binary crates via `cargo install`.

User-space (installs to ~/.cargo/bin, no sudo). Version state comes from
`cargo install --list`; there's no native version lock, so lock intent lives in
the ledger. The cargo tool itself is the driver `requires: cargo`, satisfied by the
explicit `rust` toolchain component (which `provides: cargo`).

get_latest is deferred (crates.io lookup would be a network call per inspect);
`cargo install` fetches the latest at install time.
'''

import re
import shlex

from ..driver import Driver
from ..runner import Result

# `cargo install --list` lines look like: "tree-sitter-cli v0.20.8:"
_LIST_RE = re.compile(r'^(\S+)\s+v?([^\s:]+):')
# Prefer a rustup toolchain (cargo in ~/.cargo/bin) over the distro cargo when rust is pinned to its
# `via: script` rustup binding: the non-interactive runner shell doesn't source ~/.cargo/env, so a
# bare `cargo` would be the distro's — too old for a crate's MSRV. With native rust, ~/.cargo/bin
# holds installed crate binaries but no `cargo`, so PATH falls through to the system cargo.
_CARGO_BIN = '$HOME/.cargo/bin'


class Cargo(Driver):
    name = 'cargo'
    privileged = False

    @staticmethod
    def _crate(rc):
        return rc.name  # route `name` field is the crate name

    def _cargo(self, subcmd, **kw):
        return self.runner.run(f'PATH="{_CARGO_BIN}:$PATH" cargo {subcmd}', **kw)

    # -- read -------------------------------------------------------------

    def get_version(self, rc):
        r = self._cargo('install --list')
        if not r.ok:
            return None
        crate = self._crate(rc)
        for line in r.stdout.splitlines():
            m = _LIST_RE.match(line)
            if m and m.group(1) == crate:
                return m.group(2)
        return None

    def get_latest(self, rc):
        # a `version: { crates: <name> }` route discovers the latest from crates.io
        # (cached); crates without a spec report no "latest".
        return self.resolve_version(rc)

    def is_locked(self, rc):
        return False

    # -- mutate -----------------------------------------------------------

    def install(self, rc):
        return self._cargo(f'install {shlex.quote(self._crate(rc))}', capture=False)

    def uninstall(self, rc):
        return self._cargo(f'uninstall {shlex.quote(self._crate(rc))}', capture=False)

    def upgrade(self, rc):
        # --force reinstalls at the latest version
        return self._cargo(f'install --force {shlex.quote(self._crate(rc))}', capture=False)

    def set_version(self, rc, version):
        return self._cargo(
            f'install --force --version {shlex.quote(version)} '
            f'{shlex.quote(self._crate(rc))}', capture=False)

    def lock(self, rc):
        return Result('(cargo lock recorded in ledger)', 0)

    def unlock(self, rc):
        return Result('(cargo unlock recorded in ledger)', 0)

    def location(self, rc):
        return '~/.cargo/bin'
