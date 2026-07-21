#!/usr/bin/env bash
# Runs INSIDE the openSUSE container as user `tester`. Drives a full zypper lifecycle
# through the real configsys entry point and asserts against rpm / `zypper locks`
# directly (independent of the tool). Exits non-zero on any mismatch. This is the
# on-a-real-box validation the zypper driver otherwise lacks (no host testbed).
set -euo pipefail

PKG="${PKG:-btop}"
say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

. /etc/os-release
say "target: $PRETTY_NAME (ID=$ID VERSION_ID=${VERSION_ID:-rolling})"

# `user` is the base profile that routes cleanly through native -> zypper here;
# inspect exercises the real openSUSE cascade end to end (resilient, never installs).
printf '{ configs: user }\n' > "$HOME/configsys.hu"

say "bootstrap + inspect (also builds .venv and installs humon)"
bash configsys.sh inspect

say "precondition: $PKG is NOT installed"
if rpm -q "$PKG" >/dev/null 2>&1; then fail "$PKG already installed"; fi

say "install $PKG via configsys (native -> zypper)"
bash configsys.sh install "$PKG"
rpm -q "$PKG" >/dev/null 2>&1 || fail "$PKG not installed after install"
ver=$(rpm -q --qf '%{VERSION}' "$PKG")
printf 'installed version: %s\n' "$ver"
[ -n "$ver" ] || fail "empty version after install"

# the locks table row is "N | <name> | package | (any) | ..."; match the Name column exactly.
locked() { LC_ALL=C zypper locks 2>/dev/null | grep -qE "\| *$PKG +\|"; }

say "lock $PKG via configsys (zypper addlock)"
bash configsys.sh lock "$PKG"
locked || fail "$PKG not in zypper locks after lock"

say "unlock $PKG via configsys (zypper removelock)"
bash configsys.sh unlock "$PKG"
if locked; then fail "$PKG still locked after unlock"; fi

say "remove $PKG via configsys"
bash configsys.sh remove "$PKG"
if rpm -q "$PKG" >/dev/null 2>&1; then fail "$PKG still installed after remove"; fi

say "inspect after cycle"
bash configsys.sh inspect

printf '\nPASS: full zypper install -> lock -> unlock -> remove cycle for %s on %s\n' \
    "$PKG" "$ID ${VERSION_ID:-rolling}"
