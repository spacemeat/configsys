#!/usr/bin/env bash
# Runs INSIDE the fedora:41 container as user `tester`. Drives a full dnf lifecycle
# through the real configsys entry point and asserts against rpm / dnf versionlock
# directly (independent of the tool). Exits non-zero on any mismatch.
set -euo pipefail

PKG="${PKG:-btop}"
say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

. /etc/os-release
say "target: $PRETTY_NAME (VERSION_ID=$VERSION_ID)"

# Default generated config uses the `dev` profile, whose versioned toolchains do
# not route on Fedora (deferred). Point at `user`, which is fully Fedora-routable,
# so `inspect` exercises the real fedora cascade end to end.
printf '{ configs: user }\n' > "$HOME/configsys.hu"

say "bootstrap + inspect (also builds .venv and installs humon)"
bash configsys.sh inspect

say "precondition: $PKG is NOT installed"
if rpm -q "$PKG" >/dev/null 2>&1; then fail "$PKG already installed"; fi

say "install $PKG via configsys"
bash configsys.sh install "$PKG"
rpm -q "$PKG" >/dev/null 2>&1 || fail "$PKG not installed after install"
ver=$(rpm -q --qf '%{VERSION}' "$PKG")
printf 'installed version: %s\n' "$ver"
[ -n "$ver" ] || fail "empty version after install"

say "lock $PKG via configsys (installs the versionlock plugin on demand)"
bash configsys.sh lock "$PKG"
dnf versionlock list 2>/dev/null | grep -q "Package name: $PKG" \
    || fail "$PKG not versionlocked after lock"

say "unlock $PKG via configsys"
bash configsys.sh unlock "$PKG"
if dnf versionlock list 2>/dev/null | grep -q "Package name: $PKG"; then
    fail "$PKG still versionlocked after unlock"
fi

say "remove $PKG via configsys"
bash configsys.sh remove "$PKG"
if rpm -q "$PKG" >/dev/null 2>&1; then fail "$PKG still installed after remove"; fi

say "inspect after cycle"
bash configsys.sh inspect

printf '\nPASS: full dnf install -> lock -> unlock -> remove cycle for %s on %s\n' \
    "$PKG" "$VERSION_ID"
