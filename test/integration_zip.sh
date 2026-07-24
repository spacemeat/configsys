#!/usr/bin/env bash
# Runs INSIDE a container as `tester`. Validates the tarball driver's ZIP extraction path end to
# end: deno and bun ship `.zip` release archives (not tar), and both use github's API-free
# `releases/latest/download` URL. Installs each through configsys, asserts the binary is unpacked
# and runs. Needs network (github.com downloads; NOT api.github.com). Non-zero on mismatch.
set -euo pipefail

say()  { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

. /etc/os-release
say "target: $PRETTY_NAME"

# a populated apt cache is a normal-system precondition; the minimal image wipes it
sudo apt-get update -qq >/dev/null 2>&1
printf '{ configs: user }\n' > "$HOME/configsys.hu"

say "configsys install deno (github .zip -> unzip into ~/apps/deno)"
bash configsys.sh install deno
[ -x "$HOME/apps/deno/deno" ] || fail "deno binary missing after unzip"
echo "  $("$HOME/apps/deno/deno" --version | head -1)"

say "configsys install bun (github .zip, nested dir -> ~/apps/bun)"
bash configsys.sh install bun
bun_bin="$(find "$HOME/apps/bun" -name bun -type f -perm -u+x | head -1)"
[ -n "$bun_bin" ] || fail "bun binary missing after unzip"
echo "  $("$bun_bin" --version | head -1)"

say "configsys remove deno — install dir must be gone"
bash configsys.sh remove deno
[ -e "$HOME/apps/deno/deno" ] && fail "deno still present after remove"
echo "  deno removed"

printf '\nPASS: zip extraction path (deno + bun) on %s\n' "$PRETTY_NAME"
