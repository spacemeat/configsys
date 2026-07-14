#!/usr/bin/env bash
# Build a throwaway image and run the apt integration cycle inside it. Nothing
# touches the host: all installs/removes happen in the container, discarded on exit.
#
# Usage: bash test/run-in-podman.sh [PKG]
#   PKG  apt package to exercise (default: btop)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"
PKG="${1:-btop}"
IMAGE="configsys-test:latest"

command -v podman >/dev/null 2>&1 || { echo "podman not found" >&2; exit 127; }

echo ">> building $IMAGE (context: $repo)"
podman build -q -t "$IMAGE" -f "$here/Containerfile" "$repo"

echo ">> [1/2] apt lifecycle cycle (PKG=$PKG)"
podman run --rm -e "PKG=$PKG" "$IMAGE" bash test/integration_apt.sh

echo ">> [2/2] system-prerequisite (repo-component) test (PKG=$PKG)"
podman run --rm -e "PKG=$PKG" "$IMAGE" bash test/integration_prereq.sh
