#!/usr/bin/env bash
# Gated (slow, networked) Fedora toolchain integration: installs versioned gcc/clang
# compat packages through configsys in a throwaway fedora:41 container and asserts
# the Fedora acquisition model (versioned binaries, no update-alternatives).
#
# Usage: bash test/run-fedora-toolchain-in-podman.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"
IMAGE="configsys-test:fedora"

command -v podman >/dev/null 2>&1 || { echo "podman not found" >&2; exit 127; }

echo ">> building $IMAGE (context: $repo)"
podman build -q -t "$IMAGE" -f "$here/Containerfile.fedora" "$repo"

echo ">> Fedora versioned toolchain (gcc-13, clang-18)"
podman run --rm "$IMAGE" bash test/integration_fedora_toolchain.sh
