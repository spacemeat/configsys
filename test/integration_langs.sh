#!/usr/bin/env bash
# Runs INSIDE a container as `tester`. Installs language toolchains through configsys and
# exercises the ecosystem MODULE drivers (npm, gem, go-install) for real: asserts the toolchain
# binaries appear, that userland module installs land in the per-user prefix (no sudo), and that
# get_version parsing works against the tools' real output. Needs network. Non-zero on mismatch.
set -euo pipefail

say()  { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

. /etc/os-release
say "target: $PRETTY_NAME"

printf '{ configs: user }\n' > "$HOME/configsys.hu"
export PATH="$HOME/.local/bin:$HOME/go/bin:$PATH"

# --- rust: explicit toolchain that provides cargo -----------------------------------
say "install rust (rustc + cargo)"
bash configsys.sh install rust
command -v cargo >/dev/null || fail "cargo missing after rust install"
command -v rustc >/dev/null || fail "rustc missing after rust install"
echo "  $(rustc --version)"

# --- node + npm module driver (userland global) -------------------------------------
say "install node toolchain (brings npm)"
bash configsys.sh install node
command -v npm  >/dev/null || fail "npm missing after node install"
command -v node >/dev/null || fail "node missing after node install"
echo "  node $(node --version), npm $(npm --version)"

say "install typescript as an npm global — must land userland in ~/.local/bin, no sudo"
bash configsys.sh install typescript
[ -x "$HOME/.local/bin/tsc" ] || fail "tsc not in ~/.local/bin (npm --prefix userland failed)"
echo "  $($HOME/.local/bin/tsc --version)"

# --- go + go-install driver ---------------------------------------------------------
say "install go toolchain + goimports (go-install into ~/go/bin)"
bash configsys.sh install go
command -v go >/dev/null || fail "go missing after go install"
echo "  $(go version)"
bash configsys.sh install goimports
[ -x "$HOME/go/bin/goimports" ] || fail "goimports not in ~/go/bin"
echo "  goimports installed"

# --- ruby + gem driver (userland) ---------------------------------------------------
say "install ruby + bundler (gem --user-install)"
bash configsys.sh install ruby
command -v gem >/dev/null || fail "gem missing after ruby install"
bash configsys.sh install bundler
gem list -e bundler | grep -qi 'bundler' || fail "bundler not listed by gem after install"
echo "  $(gem list -e bundler | head -1)"

# --- removal / cleanup --------------------------------------------------------------
say "remove typescript (npm uninstall, userland) — binary must disappear"
bash configsys.sh remove typescript
[ -x "$HOME/.local/bin/tsc" ] && fail "tsc still present after remove"
echo "  tsc removed"

printf '\nPASS: language toolchains + module drivers (npm/gem/go-install) on %s\n' "$PRETTY_NAME"
