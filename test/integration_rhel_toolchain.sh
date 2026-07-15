#!/usr/bin/env bash
# Runs INSIDE an EL9 (AlmaLinux) container as user `tester`. Installs versioned GCC
# via configsys (gcc-toolset SCLs) and asserts the RHEL model: the toolset installs
# under /opt/rh/gcc-toolset-N, its own gcc reports the right version, activation via
# `scl enable` works, and the system /usr/bin/gcc is untouched. Needs network.
set -euo pipefail

say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

. /etc/os-release
say "target: $PRETTY_NAME (ID=$ID VERSION_ID=$VERSION_ID) -> rhel block"

say "system gcc baseline (EL9 ships gcc 11; toolsets must not disturb it)"
sys_gcc=$(gcc --version | head -1); echo "  $sys_gcc"

for spec in "gcc-13:13" "gcc-14:14"; do
    comp=${spec%:*}; n=${spec#*:}
    say "install $comp via configsys (gcc-toolset-$n SCL)"
    bash bootstrap.sh install "$comp"
    bin="/opt/rh/gcc-toolset-$n/root/usr/bin/gcc"
    [ -x "$bin" ] || fail "$bin missing"
    "$bin" --version | grep -q " $n\." || fail "$comp toolset gcc is not version $n"
    echo "  toolset gcc: $($bin --version | head -1)"

    say "activation via scl works for gcc-toolset-$n"
    scl_ver=$(scl enable "gcc-toolset-$n" -- gcc --version | head -1)
    echo "  scl enable ...: $scl_ver"
    grep -q " $n\." <<<"$scl_ver" || fail "scl-activated gcc is not version $n"
done

say "system /usr/bin/gcc is UNCHANGED"
[ "$(gcc --version | head -1)" = "$sys_gcc" ] || fail "system gcc changed"
echo "  still: $(gcc --version | head -1)"

say "remove gcc-13 via configsys"
bash bootstrap.sh remove gcc-13
[ -x /opt/rh/gcc-toolset-13/root/usr/bin/gcc ] && fail "gcc-toolset-13 still present" || true

printf '\nPASS: EL9 versioned GCC via gcc-toolset (13, 14) install/activate/remove\n'
