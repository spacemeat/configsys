#!/usr/bin/env bash
# Runs INSIDE the fedora:41 container as user `tester`. Installs versioned compilers
# through configsys and asserts the Fedora model: versioned compat packages provide
# /usr/bin/gcc-13 etc., used directly, WITHOUT touching the system /usr/bin/gcc or
# creating an update-alternatives slot. Needs network. Exits non-zero on mismatch.
set -euo pipefail

say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

. /etc/os-release
say "target: $PRETTY_NAME (VERSION_ID=$VERSION_ID)"

printf '{ configs: user }\n' > "$HOME/configsys.hu"   # a Fedora-routable profile

say "system gcc baseline (must stay untouched by versioned installs)"
sys_gcc=$(gcc --version | head -1); echo "  $sys_gcc"

say "install gcc-13 via configsys (dnf compat packages, no update-alternatives)"
bash bootstrap.sh install gcc-13
[ -x /usr/bin/gcc-13 ] || fail "/usr/bin/gcc-13 missing"
[ -x /usr/bin/g++-13 ] || fail "/usr/bin/g++-13 missing (from gcc13-c++)"
/usr/bin/gcc-13 --version | grep -q ' 13\.' || fail "gcc-13 is not version 13"
echo "  $(/usr/bin/gcc-13 --version | head -1)"

say "system /usr/bin/gcc is UNCHANGED (no alternatives hijack)"
now_gcc=$(gcc --version | head -1)
[ "$now_gcc" = "$sys_gcc" ] || fail "/usr/bin/gcc changed: '$sys_gcc' -> '$now_gcc'"
if update-alternatives --query gcc >/dev/null 2>&1; then
    fail "an update-alternatives slot was created for gcc (should not happen on Fedora)"
fi
echo "  still: $now_gcc"

say "install clang-18 via configsys"
bash bootstrap.sh install clang-18
[ -x /usr/bin/clang-18 ] || fail "/usr/bin/clang-18 missing"
[ -x /usr/bin/clang++-18 ] || fail "/usr/bin/clang++-18 missing"
/usr/bin/clang-18 --version | grep -q 'version 18\.' || fail "clang-18 is not version 18"
echo "  $(/usr/bin/clang-18 --version | head -1)"

say "remove gcc-13 and clang-18 via configsys"
bash bootstrap.sh remove gcc-13
bash bootstrap.sh remove clang-18
if [ -x /usr/bin/gcc-13 ]; then fail "gcc-13 still present after remove"; fi
if [ -x /usr/bin/clang-18 ]; then fail "clang-18 still present after remove"; fi
[ "$(gcc --version | head -1)" = "$sys_gcc" ] || fail "system gcc changed after remove"

printf '\nPASS: Fedora versioned toolchains gcc-13 + clang-18 via dnf compat packages\n'
