#!/usr/bin/env bash
# Runs INSIDE an EL9 (AlmaLinux) container as user `tester`. Verifies that EPEL is
# enabled on demand (via the epel-release dependency) and that EPEL-only packages —
# btop and the versioned clang compat packages — install through configsys. Asserts
# against rpm / the versioned binary. Needs network.
set -euo pipefail

say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

. /etc/os-release
say "target: $PRETTY_NAME (ID=$ID) -> rhel block"
printf '{ configs: user }\n' > "$HOME/configsys.hu"

say "precondition: EPEL not yet enabled, btop absent"
if rpm -q epel-release >/dev/null 2>&1; then echo "  (epel-release already present)"; fi
if rpm -q btop >/dev/null 2>&1; then fail "btop already installed"; fi

say "install btop via configsys (pulls epel-release first, then btop from EPEL)"
bash configsys.sh install btop
rpm -q epel-release >/dev/null 2>&1 || fail "epel-release not installed (EPEL not enabled)"
rpm -q btop >/dev/null 2>&1 || fail "btop not installed (EPEL package)"
echo "  epel-release $(rpm -q --qf '%{VERSION}' epel-release); btop $(rpm -q --qf '%{VERSION}' btop)"

say "install clang-19 via configsys (clang19 compat package from EPEL)"
bash configsys.sh install clang-19
[ -x /usr/bin/clang-19 ] || fail "/usr/bin/clang-19 missing"
[ -x /usr/bin/clang++-19 ] || fail "/usr/bin/clang++-19 missing"
/usr/bin/clang-19 --version | grep -q "version 19\." || fail "clang-19 is not version 19"
echo "  $(/usr/bin/clang-19 --version | head -1)"

say "remove btop and clang-19 via configsys"
bash configsys.sh remove btop
bash configsys.sh remove clang-19
if rpm -q btop >/dev/null 2>&1; then fail "btop still installed after remove"; fi
if [ -x /usr/bin/clang-19 ]; then fail "clang-19 still present after remove"; fi

printf '\nPASS: EL EPEL enablement (btop) + versioned clang (clang-19) via configsys\n'
