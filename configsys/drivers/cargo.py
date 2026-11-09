'''cargo.py — the cargo driver: Rust binary crates via `cargo install`.

User-space (installs to ~/.cargo/bin, no sudo). Version state comes from
`cargo install --list`; there's no native version lock, so lock intent lives in
the ledger. The cargo tool itself is the driver `requires: cargo`, satisfied by the
explicit `rust` toolchain component (which `provides: cargo`).

get_latest is deferred (crates.io lookup would be a network call per inspect);
`cargo install` fetches the latest at install time.
'''

import re

from ._module import ModuleDriver

# `cargo install --list` lines look like: "tree-sitter-cli v0.20.8:"
_LIST_RE = re.compile(r'^(\S+)\s+v?([^\s:]+):')
# Prefer a rustup toolchain (cargo in ~/.cargo/bin) over the distro cargo when rust is pinned to its
# `via: script` rustup binding: the non-interactive runner shell doesn't source ~/.cargo/env, so a
# bare `cargo` would be the distro's — too old for a crate's MSRV. With native rust, ~/.cargo/bin
# holds installed crate binaries but no `cargo`, so PATH falls through to the system cargo.
_CARGO_BIN = '$HOME/.cargo/bin'


class Cargo(ModuleDriver):
    name = 'cargo'
    TOOL = f'PATH="{_CARGO_BIN}:$PATH" cargo'
    CMDS = {'install': '{tool} install {pkg}',
            'uninstall': '{tool} uninstall {pkg}',
            'upgrade': '{tool} install --force {pkg}',          # --force reinstalls at the latest
            'set_version': '{tool} install --force --version {ver} {pkg}'}
    LIST_CMD = '{tool} install --list'                          # every installed crate, one call
    BIN_DIR = '~/.cargo/bin'

    def parse_list(self, stdout):
        out = {}
        for line in stdout.splitlines():
            m = _LIST_RE.match(line)
            if m:
                out[m.group(1)] = m.group(2)
        return out
