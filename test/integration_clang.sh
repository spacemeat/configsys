#!/usr/bin/env bash
# Runs INSIDE the ubuntu:22.04 (jammy) container as user `tester`. Drives a real
# clang install through the configsys entry point: adds the apt.llvm.org repo,
# installs clang-N, and registers the update-alternatives group — then asserts
# against the filesystem / update-alternatives directly. Exits non-zero on any
# mismatch. Needs network (LLVM repo + package download).
set -euo pipefail

VER="${VER:-18}"
COMP="clang-$VER"
say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

say "refresh apt lists (image ships them cleaned; deps install before the LLVM repo)"
sudo apt-get update -qq

say "bootstrap + inspect (builds .venv, installs humon)"
bash bootstrap.sh inspect

say "precondition: $COMP is NOT installed"
if [ -x "/usr/bin/$COMP" ]; then fail "$COMP already present"; fi

say "install $COMP via configsys (LLVM repo + alternatives)"
bash bootstrap.sh install "$COMP"

say "master + slave binaries exist"
[ -x "/usr/bin/clang-$VER" ]   || fail "/usr/bin/clang-$VER missing"
[ -x "/usr/bin/clang++-$VER" ] || fail "/usr/bin/clang++-$VER missing (slave target)"

say "update-alternatives registered clang with clang++ slaved"
q=$(update-alternatives --query clang)
grep -q "/usr/bin/clang-$VER" <<<"$q" || fail "clang-$VER not an alternative for clang"
grep -q "clang++" <<<"$q"             || fail "clang++ not registered as a slave"

say "/usr/bin/clang and /usr/bin/clang++ resolve to version $VER"
cv=$(/usr/bin/clang --version | head -1)
grep -q "version $VER" <<<"$cv" || fail "clang reports wrong version: $cv"
xv=$(/usr/bin/clang++ --version | head -1)
grep -q "version $VER" <<<"$xv" || fail "clang++ reports wrong version: $xv"
printf 'clang:   %s\nclang++: %s\n' "$cv" "$xv"

say "remove $COMP via configsys"
bash bootstrap.sh remove "$COMP"
if dpkg -s "clang-$VER" 2>/dev/null | grep -q '^Status: install ok installed'; then
    fail "clang-$VER still installed after remove"
fi
if update-alternatives --query clang 2>/dev/null | grep -q "/usr/bin/clang-$VER"; then
    fail "clang-$VER still an alternative after remove"
fi

printf '\nPASS: full clang install -> alternatives -> remove cycle for %s\n' "$COMP"
