#!/usr/bin/env bash
# Build a throwaway EL9 image and run the RPM Fusion / EPEL / kicad-unroutable cycle
# inside it. Nothing touches the host: all installs/removes happen in the container.
# AlmaLinux 9 is a free EL rebuild (ID=almalinux -> rhel block) with the `crb` repo.
#
# Usage: bash test/run-el-rpmfusion-in-podman.sh [EL_IMAGE]
#   EL_IMAGE  base image (default: almalinux:9; rockylinux/rockylinux:9 also works)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"
EL_IMAGE="${1:-almalinux:9}"
IMAGE="configsys-test:el9"

command -v podman >/dev/null 2>&1 || { echo "podman not found" >&2; exit 127; }

echo ">> building $IMAGE from $EL_IMAGE (context: $repo)"
podman build -q -t "$IMAGE" --build-arg "EL_IMAGE=$EL_IMAGE" \
    -f "$here/Containerfile.el9" "$repo"

echo ">> EL RPM Fusion / EPEL / kicad-unroutable cycle"
podman run --rm "$IMAGE" bash test/integration_el_rpmfusion.sh
