#!/usr/bin/env bash
# Runs INSIDE the ubuntu:22.04 container as user `tester`. Drives a full apt
# lifecycle through the real configsys entry point and asserts against dpkg /
# apt-mark directly (independent of the tool). Exits non-zero on any mismatch.
#
# Note: checks use here-strings (grep ... <<<"$var") rather than `cmd | grep -q`
# so that grep -q closing the pipe early can't SIGPIPE the producer under
# `set -o pipefail`.
set -euo pipefail

PKG="${PKG:-btop}"
say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

say "refresh apt lists"
sudo apt-get update -qq

say "confirm a candidate exists for '$PKG'"
policy=$(apt-cache policy "$PKG")
grep -q 'Candidate: [0-9]' <<<"$policy" || fail "no install candidate for $PKG"

say "bootstrap + inspect (also builds .venv and installs humon)"
bash configsys.sh inspect

say "precondition: $PKG is NOT installed"
if dpkg -s "$PKG" >/dev/null 2>&1; then fail "$PKG already installed"; fi

say "install $PKG via configsys"
bash configsys.sh install "$PKG"
dpkg -s "$PKG" >/dev/null 2>&1 || fail "$PKG not installed after install"
ver=$(dpkg-query -W -f='${Version}' "$PKG")
printf 'installed version: %s\n' "$ver"
[ -n "$ver" ] || fail "empty version after install"

say "lock $PKG via configsys"
bash configsys.sh lock "$PKG"
grep -qx "$PKG" <<<"$(apt-mark showhold)" || fail "$PKG not held after lock"
grep -q "$PKG" "$HOME/.config/configsys/state.hu" || fail "lock intent not in ledger"

say "unlock $PKG via configsys"
bash configsys.sh unlock "$PKG"
if grep -qx "$PKG" <<<"$(apt-mark showhold)"; then fail "$PKG still held after unlock"; fi

say "remove $PKG via configsys"
bash configsys.sh remove "$PKG"
status=$(dpkg -s "$PKG" 2>/dev/null || true)
if grep -q '^Status: install ok installed' <<<"$status"; then fail "$PKG still installed after remove"; fi

say "inspect after cycle"
bash configsys.sh inspect

printf '\nPASS: full apt install -> lock -> unlock -> remove cycle for %s\n' "$PKG"
