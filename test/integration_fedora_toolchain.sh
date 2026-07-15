#!/usr/bin/env bash
# Runs INSIDE a Fedora container as user `tester`. Installs versioned compilers
# through configsys and asserts the Fedora model: versioned compat packages provide
# /usr/bin/gcc-N etc., used directly, WITHOUT touching the system /usr/bin/gcc or
# creating an update-alternatives slot. Release-aware — the gccNN compat window
# moves each release. Needs network. Exits non-zero on mismatch.
set -euo pipefail

say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

. /etc/os-release
say "target: $PRETTY_NAME (VERSION_ID=$VERSION_ID)"

# The routable gcc version depends on the release (see the fedora@N route variants).
case "$VERSION_ID" in
    41) GCC_COMP=gcc-13; GCC_N=13 ;;
    42) GCC_COMP=gcc-14; GCC_N=14 ;;
    *)  GCC_COMP=gcc-13; GCC_N=13 ;;
esac
CLANG_COMP=clang-18; CLANG_N=18      # clang18 compat exists on 41 and 42

printf '{ configs: user }\n' > "$HOME/configsys.hu"   # a Fedora-routable profile

say "system gcc baseline (must stay untouched by versioned installs)"
sys_gcc=$(gcc --version | head -1); echo "  $sys_gcc"

say "install $GCC_COMP via configsys (dnf compat packages, no update-alternatives)"
bash bootstrap.sh install "$GCC_COMP"
[ -x "/usr/bin/gcc-$GCC_N" ] || fail "/usr/bin/gcc-$GCC_N missing"
[ -x "/usr/bin/g++-$GCC_N" ] || fail "/usr/bin/g++-$GCC_N missing (from gccNN-c++)"
"/usr/bin/gcc-$GCC_N" --version | grep -q " $GCC_N\." || fail "gcc-$GCC_N is not version $GCC_N"
echo "  $(/usr/bin/gcc-$GCC_N --version | head -1)"

say "system /usr/bin/gcc is UNCHANGED (no alternatives hijack)"
now_gcc=$(gcc --version | head -1)
[ "$now_gcc" = "$sys_gcc" ] || fail "/usr/bin/gcc changed: '$sys_gcc' -> '$now_gcc'"
if update-alternatives --query gcc >/dev/null 2>&1; then
    fail "an update-alternatives slot was created for gcc (should not happen on Fedora)"
fi
echo "  still: $now_gcc"

say "install $CLANG_COMP via configsys"
bash bootstrap.sh install "$CLANG_COMP"
[ -x "/usr/bin/clang-$CLANG_N" ] || fail "/usr/bin/clang-$CLANG_N missing"
[ -x "/usr/bin/clang++-$CLANG_N" ] || fail "/usr/bin/clang++-$CLANG_N missing"
"/usr/bin/clang-$CLANG_N" --version | grep -q "version $CLANG_N\." || fail "clang not v$CLANG_N"
echo "  $(/usr/bin/clang-$CLANG_N --version | head -1)"

say "remove $GCC_COMP and $CLANG_COMP via configsys"
bash bootstrap.sh remove "$GCC_COMP"
bash bootstrap.sh remove "$CLANG_COMP"
if [ -x "/usr/bin/gcc-$GCC_N" ]; then fail "gcc-$GCC_N still present after remove"; fi
if [ -x "/usr/bin/clang-$CLANG_N" ]; then fail "clang-$CLANG_N still present after remove"; fi
[ "$(gcc --version | head -1)" = "$sys_gcc" ] || fail "system gcc changed after remove"

printf '\nPASS: Fedora %s versioned toolchains (%s, %s) via dnf compat packages\n' \
    "$VERSION_ID" "$GCC_COMP" "$CLANG_COMP"
