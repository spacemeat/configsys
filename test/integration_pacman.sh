#!/usr/bin/env bash
# Runs INSIDE the archlinux container as user `tester`. Drives a full pacman
# lifecycle through the real configsys entry point and asserts against pacman / the
# ledger directly. Arch is rolling, so lock is ledger-only (no native hold).
set -euo pipefail

PKG="${PKG:-btop}"
say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

. /etc/os-release
say "target: $PRETTY_NAME (ID=$ID) — rolling"
printf '{ configs: user }\n' > "$HOME/configsys.hu"

say "bootstrap + inspect (also builds .venv and installs humon)"
bash bootstrap.sh inspect

say "precondition: $PKG is NOT installed"
if pacman -Q "$PKG" >/dev/null 2>&1; then fail "$PKG already installed"; fi

say "install $PKG via configsys"
bash bootstrap.sh install "$PKG"
pacman -Q "$PKG" >/dev/null 2>&1 || fail "$PKG not installed after install"
ver=$(pacman -Q "$PKG" | awk '{print $2}')
printf 'installed version: %s\n' "$ver"
[ -n "$ver" ] || fail "empty version after install"

say "lock $PKG via configsys (ledger-only — pacman is rolling)"
bash bootstrap.sh lock "$PKG"
grep -q "$PKG" "$HOME/.config/configsys/state.hu" || fail "lock intent not in ledger"

say "unlock $PKG via configsys"
bash bootstrap.sh unlock "$PKG"

say "remove $PKG via configsys"
bash bootstrap.sh remove "$PKG"
if pacman -Q "$PKG" >/dev/null 2>&1; then fail "$PKG still installed after remove"; fi

say "inspect after cycle"
bash bootstrap.sh inspect

printf '\nPASS: full pacman install -> lock -> unlock -> remove cycle for %s\n' "$PKG"
