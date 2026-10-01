#!/usr/bin/env bash
# Build a throwaway Void (glibc) image and run the xbps/runit integration cycle inside it.
#
# Usage: bash test/run-xbps-in-podman.sh [PKG]
#   PKG  xbps package to exercise (default: btop)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"
PKG="${1:-btop}"
IMAGE="configsys-test:void"
SEC=(--security-opt seccomp=unconfined)   # xbps's extraction trips rootless podman's seccomp

command -v podman >/dev/null 2>&1 || { echo "podman not found" >&2; exit 127; }

echo ">> building $IMAGE (context: $repo)"
podman build -q "${SEC[@]}" -t "$IMAGE" -f "$here/Containerfile.void" "$repo"

echo ">> xbps lifecycle + Void routing (PKG=$PKG)"
podman run --rm "${SEC[@]}" -e "PKG=$PKG" "$IMAGE" bash test/integration_xbps.sh
