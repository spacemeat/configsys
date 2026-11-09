#!/usr/bin/env bash
# Build a throwaway fedora image (default 45) and run the dnf integration cycle inside it.
# Nothing touches the host: all installs/removes happen in the container.
#
# Usage: [FEDORA=45] bash test/run-dnf-in-podman.sh [PKG]
#   PKG     dnf package to exercise (default: btop)
#   FEDORA  the release to test on (default 45, the newest released) — a new release's driver-lifecycle check (/update-os)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"
PKG="${1:-btop}"
FEDORA="${FEDORA:-45}"
IMAGE="configsys-test:fedora-$FEDORA"

command -v podman >/dev/null 2>&1 || { echo "podman not found" >&2; exit 127; }

echo ">> building $IMAGE (context: $repo)"
podman build -q -t "$IMAGE" --build-arg "FEDORA=$FEDORA" -f "$here/Containerfile.fedora" "$repo"

echo ">> [1/2] dnf lifecycle cycle (PKG=$PKG)"
podman run --rm -e "PKG=$PKG" "$IMAGE" bash test/integration_dnf.sh

echo ">> [2/2] dev/graphics gaps (build toolchain + vulkan X libs)"
podman run --rm "$IMAGE" bash test/integration_fedora_devgaps.sh
