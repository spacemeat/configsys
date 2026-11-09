#!/usr/bin/env bash
# Runs INSIDE an apt container as user `tester`. Where fastfetch isn't in the release's apt repos,
# configsys installs the official github .deb (native-pkg-file: resolve the release version,
# download the asset, apt-get install it); where the release packages it (Ubuntu 26.04+, Debian
# 13+), the native package. Asserts it lands on PATH and in dpkg either way. Needs network.
set -euo pipefail

say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

. /etc/os-release
say "target: $PRETTY_NAME"
sudo apt-get update -qq

if apt-cache show fastfetch >/dev/null 2>&1; then
    say "fastfetch is packaged on this release: configsys routes the native package"
    bash configsys.sh where fastfetch | grep -q 'default: via native' \
        || fail "packaged here, but configsys doesn't route the native package"
else
    say "fastfetch isn't packaged here: configsys installs the official github .deb"
fi
bash configsys.sh install fastfetch
command -v fastfetch >/dev/null 2>&1 || fail "fastfetch not on PATH after install"
dpkg -l fastfetch 2>/dev/null | grep -q '^ii' || fail "fastfetch .deb not registered in dpkg"
echo "  $(fastfetch --version); dpkg: $(dpkg-query -W -f='${Version}' fastfetch)"

say "remove fastfetch via configsys"
bash configsys.sh remove fastfetch
if command -v fastfetch >/dev/null 2>&1; then fail "fastfetch still on PATH after remove"; fi

printf '\nPASS: fastfetch on %s (native where packaged, else the github .deb)\n' "$VERSION_ID"
