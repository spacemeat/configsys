#!/usr/bin/env bash
# Runs INSIDE a container as `tester`. Validates the opam/luarocks/cabal module drivers against
# the REAL tools. luarocks gets a full configsys round-trip (pulls the tool, installs a pure-Lua
# rock userland with --local, lists it, removes it). opam and cabal have heavy backends (opam
# needs `opam init`; cabal needs ghc), so here we confirm their driver READ-commands parse
# against the real CLIs — the mutating commands are recon-verified (opam 2.1.5 / cabal 3.8.1).
# Needs network. Non-zero on mismatch.
set -euo pipefail

say()  { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

. /etc/os-release
say "target: $PRETTY_NAME"

printf '{ configs: user }\n' > "$HOME/configsys.hu"
export PATH="$HOME/.luarocks/bin:$PATH"

# --- luarocks: full configsys path (tool + userland rock) ---------------------------
say "configsys install dkjson (pulls luarocks, installs the rock with --local)"
bash configsys.sh install dkjson
command -v luarocks >/dev/null || fail "luarocks tool missing after install"
luarocks list --porcelain dkjson | grep -q '^dkjson' || fail "dkjson not in 'luarocks list --porcelain'"
echo "  $(luarocks list --porcelain dkjson | head -1)"

say "configsys remove dkjson"
bash configsys.sh remove dkjson
luarocks list --porcelain dkjson | grep -q '^dkjson' && fail "dkjson still listed after remove"
echo "  dkjson removed"

# --- opam / cabal: their backends are heavy (opam init / ghc), so validate the property that
# actually matters for `configsys inspect` — the drivers' get_version runs against the REAL tools
# and DEGRADES to None (not a crash) when uninitialized/empty. Mutating commands are recon-verified.
say "install opam + cabal tools (apt); driver get_version must degrade to None, not crash"
sudo apt-get install -y -qq opam cabal-install >/dev/null 2>&1
opam  --version >/dev/null 2>&1 || fail "opam tool not installed"
cabal --version >/dev/null 2>&1 || fail "cabal tool not installed"
echo "  opam $(opam --version), cabal $(cabal --version | head -1 | awk '{print $NF}')"

.venv/bin/python - <<'PY' || fail "a module driver get_version raised against the real tool"
from configsys.runner import Runner
from configsys.componentObj import ResolvedComponent
from configsys.drivers.opam import Opam
from configsys.drivers.cabal import Cabal
r = Runner()
def rc(drv, name): return ResolvedComponent(key=f'{drv}\\{name}', driver=drv, comp=name,
                                            fields={'name': name})
assert Opam(r).get_version(rc('opam', 'dune')) is None, 'opam should read None when uninitialized'
assert Cabal(r).get_version(rc('cabal', 'hlint')) is None, 'cabal should read None when empty'
print('  opam & cabal get_version -> None (graceful against the real, uninitialized CLIs)')
PY

printf '\nPASS: luarocks full round-trip + opam/cabal graceful reads on %s\n' "$PRETTY_NAME"
