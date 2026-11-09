#!/usr/bin/env bash
# Build a throwaway image and run the apt integration cycle inside it. Nothing
# touches the host: all installs/removes happen in the container, discarded on exit.
#
# Usage: [BASE=ubuntu:26.04] bash test/run-in-podman.sh [PKG]
#   PKG   apt package to exercise (default: btop)
#   BASE  the base image (default ubuntu:22.04; a debian:N image works too) — a new release's
#         driver-lifecycle check (/update-os)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"
PKG="${1:-btop}"
BASE="${BASE:-ubuntu:22.04}"
IMAGE="configsys-test:latest"
[ "$BASE" = ubuntu:22.04 ] || IMAGE="configsys-test:apt-${BASE//[^A-Za-z0-9.]/-}"

command -v podman >/dev/null 2>&1 || { echo "podman not found" >&2; exit 127; }

echo ">> building $IMAGE from $BASE (context: $repo)"
podman build -q -t "$IMAGE" --build-arg "BASE=$BASE" -f "$here/Containerfile" "$repo"

echo ">> [1/4] apt lifecycle cycle (PKG=$PKG)"
podman run --rm -e "PKG=$PKG" "$IMAGE" bash test/integration_apt.sh

echo ">> [2/4] system-prerequisite (repo-component) test (PKG=$PKG)"
podman run --rm -e "PKG=$PKG" "$IMAGE" bash test/integration_prereq.sh

echo ">> [3/4] i386 multiarch prereq (behind native Steam)"
podman run --rm "$IMAGE" bash test/integration_i386_multiarch.sh

echo ">> [4/4] fastfetch via github .deb (apt deb mode)"
podman run --rm "$IMAGE" bash test/integration_fastfetch_deb.sh
