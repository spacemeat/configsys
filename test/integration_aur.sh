#!/usr/bin/env bash
# Runs INSIDE the archlinux container as user `tester`. Builds an AUR package through
# configsys (git clone + makepkg -si, no helper) and asserts it landed in the pacman
# db and on PATH. Uses yay-bin (a small prebuilt AUR package). Needs network.
set -euo pipefail

say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

. /etc/os-release
say "target: $PRETTY_NAME (ID=$ID)"
printf '{ configs: user }\n' > "$HOME/configsys.hu"

say "precondition: yay not installed"
if pacman -Q yay-bin >/dev/null 2>&1; then fail "yay-bin already installed"; fi

say "install yay via configsys (AUR: base-devel/git deps, then makepkg -si)"
bash configsys.sh install yay
pacman -Q yay-bin >/dev/null 2>&1 || fail "yay-bin not in pacman db after build"
command -v yay >/dev/null 2>&1 || fail "yay not on PATH"
echo "  installed: $(pacman -Q yay-bin); binary: $(command -v yay)"

say "remove yay via configsys (pacman -R)"
bash configsys.sh remove yay
if pacman -Q yay-bin >/dev/null 2>&1; then fail "yay-bin still installed after remove"; fi

printf '\nPASS: AUR package build/install/remove via configsys (yay-bin)\n'
