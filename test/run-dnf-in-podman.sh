#!/usr/bin/env bash
# Build a throwaway fedora:41 image and run the dnf integration cycle inside it.
# Nothing touches the host: all installs/removes happen in the container.
#
# Usage: bash test/run-dnf-in-podman.sh [PKG]
#   PKG  dnf package to exercise (default: btop)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"
PKG="${1:-btop}"
IMAGE="configsys-test:fedora"

command -v podman >/dev/null 2>&1 || { echo "podman not found" >&2; exit 127; }

echo ">> building $IMAGE (context: $repo)"
podman build -q -t "$IMAGE" -f "$here/Containerfile.fedora" "$repo"

echo ">> dnf lifecycle cycle (PKG=$PKG)"
podman run --rm -e "PKG=$PKG" "$IMAGE" bash test/integration_dnf.sh
