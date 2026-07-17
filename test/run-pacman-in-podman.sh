#!/usr/bin/env bash
# Build a throwaway Arch image and run the pacman integration cycle inside it.
#
# Usage: bash test/run-pacman-in-podman.sh [PKG]
#   PKG  pacman package to exercise (default: btop)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"
PKG="${1:-btop}"
IMAGE="configsys-test:arch"

command -v podman >/dev/null 2>&1 || { echo "podman not found" >&2; exit 127; }

echo ">> building $IMAGE (context: $repo)"
podman build -q -t "$IMAGE" -f "$here/Containerfile.arch" "$repo"

echo ">> [1/2] pacman lifecycle cycle (PKG=$PKG)"
podman run --rm -e CONFIGSYS_RESOLVER -e "PKG=$PKG" "$IMAGE" bash test/integration_pacman.sh

echo ">> [2/3] AUR build/install/remove (makepkg)"
podman run --rm -e CONFIGSYS_RESOLVER "$IMAGE" bash test/integration_aur.sh

echo ">> [3/3] Arch vulkan-dev pieces (build-essential, xcb, Vulkan runtime)"
podman run --rm -e CONFIGSYS_RESOLVER "$IMAGE" bash test/integration_arch_graphics.sh
