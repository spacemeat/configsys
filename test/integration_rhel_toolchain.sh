#!/usr/bin/env bash
# Runs INSIDE an EL (AlmaLinux 9/10) container as user `tester`. Installs versioned GCC via
# configsys (gcc-toolset SCLs — whichever this release ships: EL 9 has 12-15, EL 10 only 15) and
# asserts the RHEL model: the toolset installs
# under /opt/rh/gcc-toolset-N, its own gcc reports the right version, activation via
# `scl enable` works, and the system /usr/bin/gcc is untouched. Needs network.
set -euo pipefail

say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

. /etc/os-release
say "target: $PRETTY_NAME (ID=$ID VERSION_ID=$VERSION_ID) -> rhel block"

say "system gcc baseline (EL9 ships gcc 11; toolsets must not disturb it)"
sys_gcc=$(gcc --version | head -1); echo "  $sys_gcc"

# the toolsets THIS release ships (newest two), so the harness follows the release
mapfile -t avail < <(dnf -q list --available 'gcc-toolset-[0-9]*' 2>/dev/null \
    | sed -nE 's/^gcc-toolset-([0-9]+)\.(x86_64|aarch64).*/\1/p' | sort -n | uniq | tail -2)
[ "${#avail[@]}" -gt 0 ] || fail "no gcc-toolset on this release"
specs=(); for n in "${avail[@]}"; do specs+=("gcc-$n:$n"); done
first=${avail[0]}
for spec in "${specs[@]}"; do
    comp=${spec%:*}; n=${spec#*:}
    say "install $comp via configsys (gcc-toolset-$n SCL)"
    bash configsys.sh install "$comp"
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

say "remove gcc-$first via configsys"
bash configsys.sh remove "gcc-$first"
[ -x "/opt/rh/gcc-toolset-$first/root/usr/bin/gcc" ] && fail "gcc-toolset-$first still present" || true

printf '\nPASS: EL %s versioned GCC via gcc-toolset (%s) install/activate/remove\n' "$VERSION_ID" "${avail[*]}"
