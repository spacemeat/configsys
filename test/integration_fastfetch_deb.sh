#!/usr/bin/env bash
# Runs INSIDE the ubuntu:22.04 container as user `tester`. fastfetch isn't in any
# Ubuntu apt repo, so configsys installs the official github .deb (apt `deb` mode:
# resolve the release version, download the asset, apt-get install it). Asserts it
# lands on PATH and in dpkg. Needs network (github API + release download).
set -euo pipefail

say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

. /etc/os-release
say "target: $PRETTY_NAME"
printf '{ configs: user }\n' > "$HOME/configsys.hu"
sudo apt-get update -qq

say "confirm fastfetch is NOT in the apt repos here (the whole reason for deb mode)"
if apt-cache show fastfetch >/dev/null 2>&1; then fail "unexpectedly in apt repos"; fi
echo "  not in repos, as expected"

say "install fastfetch via configsys (downloads the official github .deb)"
bash bootstrap.sh install fastfetch
command -v fastfetch >/dev/null 2>&1 || fail "fastfetch not on PATH after install"
dpkg -l fastfetch 2>/dev/null | grep -q '^ii' || fail "fastfetch .deb not registered in dpkg"
echo "  $(fastfetch --version); dpkg: $(dpkg-query -W -f='${Version}' fastfetch)"

say "remove fastfetch via configsys"
bash bootstrap.sh remove fastfetch
if command -v fastfetch >/dev/null 2>&1; then fail "fastfetch still on PATH after remove"; fi

printf '\nPASS: fastfetch via the github .deb (apt deb mode) on %s\n' "$VERSION_ID"
