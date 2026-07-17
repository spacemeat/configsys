#!/usr/bin/env bash
# Gated (slow, networked) clang integration. Builds the shared test image and runs
# the clang install -> update-alternatives -> remove cycle inside a throwaway
# container. Adds the apt.llvm.org repo and downloads clang-N, so it is
# intentionally NOT part of run-in-podman.sh.
#
# Usage: bash test/run-clang-in-podman.sh [VER]
#   VER  clang major version to exercise (default: 18)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"
VER="${1:-18}"
IMAGE="configsys-test:latest"

command -v podman >/dev/null 2>&1 || { echo "podman not found" >&2; exit 127; }

echo ">> building $IMAGE (context: $repo)"
podman build -q -t "$IMAGE" -f "$here/Containerfile" "$repo"

echo ">> clang lifecycle (VER=$VER, LLVM apt repo + update-alternatives)"
podman run --rm -e CONFIGSYS_RESOLVER -e "VER=$VER" "$IMAGE" bash test/integration_clang.sh
