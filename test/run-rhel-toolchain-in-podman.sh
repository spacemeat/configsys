#!/usr/bin/env bash
# Gated (slow, networked) RHEL-family gcc-toolset integration. Uses AlmaLinux 9 (a
# free RHEL-binary-compatible EL9 image) in a throwaway container.
#
# Usage: bash test/run-rhel-toolchain-in-podman.sh [EL_IMAGE]
#   EL_IMAGE  base image (default: almalinux:9; e.g. rockylinux:9)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"
EL_IMAGE="${1:-almalinux:9}"
IMAGE="configsys-test:el9"

command -v podman >/dev/null 2>&1 || { echo "podman not found" >&2; exit 127; }

echo ">> building $IMAGE (base: $EL_IMAGE)"
podman build -q -t "$IMAGE" --build-arg "EL_IMAGE=$EL_IMAGE" -f "$here/Containerfile.el9" "$repo"

echo ">> EL9 gcc-toolset integration"
podman run --rm "$IMAGE" bash test/integration_rhel_toolchain.sh
