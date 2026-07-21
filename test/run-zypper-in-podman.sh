#!/usr/bin/env bash
# Build a throwaway openSUSE image and run the zypper integration cycle inside it.
# Nothing touches the host: all installs/removes happen in the container.
#
# Usage: bash test/run-zypper-in-podman.sh [PKG] [SUSE_IMAGE]
#   PKG         zypper package to exercise (default: btop)
#   SUSE_IMAGE  base image (default: Tumbleweed — the rolling, current-python target)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"
PKG="${1:-btop}"
SUSE_IMAGE="${2:-registry.opensuse.org/opensuse/tumbleweed:latest}"
IMAGE="configsys-test:opensuse"

command -v podman >/dev/null 2>&1 || { echo "podman not found" >&2; exit 127; }

echo ">> building $IMAGE from $SUSE_IMAGE (context: $repo)"
podman build -q -t "$IMAGE" --build-arg "SUSE_IMAGE=$SUSE_IMAGE" \
    -f "$here/Containerfile.opensuse" "$repo"

echo ">> zypper lifecycle cycle (PKG=$PKG)"
podman run --rm -e "PKG=$PKG" "$IMAGE" bash test/integration_zypper.sh
