#!/usr/bin/env bash
# Runs INSIDE a Fedora container as user `tester`. Installs the components that were
# the Fedora dev/graphics gaps — the build toolchain (c-toolchain + cpp-toolchain + make, which
# replaced the old build-essential bundle) and
# the vulkan X-dev libs — through configsys, and asserts via rpm. Skips the large
# vulkan-sdk tarball (OS-agnostic, covered elsewhere). Needs network.
set -euo pipefail

say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

. /etc/os-release
say "target: $PRETTY_NAME"
say "install c-toolchain + cpp-toolchain + make via configsys (gcc, gcc-c++, make)"
bash configsys.sh install c-toolchain cpp-toolchain make
for p in gcc gcc-c++ make; do
    rpm -q "$p" >/dev/null 2>&1 || fail "$p not installed"
    echo "  $p $(rpm -q --qf '%{VERSION}' "$p")"
done

say "install the vulkan X-dev libs via configsys"
bash configsys.sh install libxcb-devel
bash configsys.sh install xcb-util-cursor-devel
for p in libxcb-devel xcb-util-cursor-devel; do
    rpm -q "$p" >/dev/null 2>&1 || fail "$p not installed"
    echo "  $p $(rpm -q --qf '%{VERSION}' "$p")"
done

say "libxcb-devel provides the xinput + xinerama headers (the Debian trio)"
[ -e /usr/include/xcb/xinput.h ]    || fail "xinput.h missing"
[ -e /usr/include/xcb/xinerama.h ]  || fail "xinerama.h missing"
echo "  /usr/include/xcb/xinput.h + xinerama.h present"

say "remove make via configsys"
bash configsys.sh remove make
if rpm -q make >/dev/null 2>&1; then fail "make still installed after remove"; fi

printf '\nPASS: Fedora dev/graphics gaps (build toolchain + vulkan X libs)\n'
