#!/usr/bin/env bash
# Runs INSIDE the archlinux container as user `tester`. Installs the Arch-specific
# vulkan-dev pieces through configsys (build-essential -> gcc+make, the xcb libs,
# and the split Vulkan runtime) and asserts via pacman / the ICD manifests. Skips
# the large vulkan-sdk tarball (OS-agnostic, covered elsewhere). Needs network.
set -euo pipefail

say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

. /etc/os-release
say "target: $PRETTY_NAME (ID=$ID)"
printf '{ configs: user }\n' > "$HOME/configsys.hu"

say "install build-essential via configsys (Arch: gcc + make; gcc bundles g++)"
bash configsys.sh install build-essential
for p in gcc make; do pacman -Q "$p" >/dev/null 2>&1 || fail "$p not installed"; done
command -v g++ >/dev/null 2>&1 || fail "g++ missing (should come with gcc on Arch)"
echo "  gcc $(pacman -Q gcc | awk '{print $2}'), make $(pacman -Q make | awk '{print $2}'), g++ present"

say "install the vulkan-dev X libs (libxcb bundles xinput + xinerama)"
bash configsys.sh install libxcb
bash configsys.sh install xcb-util-cursor
pacman -Q libxcb >/dev/null 2>&1 || fail "libxcb not installed"
pacman -Q xcb-util-cursor >/dev/null 2>&1 || fail "xcb-util-cursor not installed"
[ -e /usr/lib/libxcb-xinput.so.0 ] && [ -e /usr/lib/libxcb-xinerama.so.0 ] \
    || fail "libxcb did not provide xinput/xinerama"
echo "  libxcb provides xinput + xinerama"

say "install vulkan-runtime (Arch: loader + radeon + intel + swrast)"
bash configsys.sh install vulkan-runtime
for p in vulkan-icd-loader vulkan-radeon vulkan-intel vulkan-swrast; do
    pacman -Q "$p" >/dev/null 2>&1 || fail "$p not installed"
done
say "Vulkan ICD manifests registered (radeon/intel/lavapipe)"
icds=$(ls /usr/share/vulkan/icd.d/ 2>/dev/null)
echo "$icds" | sed 's/^/  /'
grep -q radeon <<<"$icds" || fail "no radeon ICD manifest"
grep -q lvp    <<<"$icds" || fail "no lavapipe (software) ICD manifest"

printf '\nPASS: Arch vulkan-dev pieces (build-essential, xcb libs, split Vulkan runtime)\n'
