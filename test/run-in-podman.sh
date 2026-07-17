#!/usr/bin/env bash
# Build a throwaway image and run the apt integration cycle inside it. Nothing
# touches the host: all installs/removes happen in the container, discarded on exit.
#
# Usage: bash test/run-in-podman.sh [PKG]
#   PKG  apt package to exercise (default: btop)
#
# Resolver: set CONFIGSYS_RESOLVER=v2 to validate the v2 capability/component engine
# (routes2.hu) instead of the live RouteResolver — it is forwarded into the containers.
#   CONFIGSYS_RESOLVER=v2 bash test/run-in-podman.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"
PKG="${1:-btop}"
IMAGE="configsys-test:latest"

command -v podman >/dev/null 2>&1 || { echo "podman not found" >&2; exit 127; }

echo ">> building $IMAGE (context: $repo)"
podman build -q -t "$IMAGE" -f "$here/Containerfile" "$repo"

echo ">> [1/3] apt lifecycle cycle (PKG=$PKG)"
podman run --rm -e CONFIGSYS_RESOLVER -e "PKG=$PKG" "$IMAGE" bash test/integration_apt.sh

echo ">> [2/3] system-prerequisite (repo-component) test (PKG=$PKG)"
podman run --rm -e CONFIGSYS_RESOLVER -e "PKG=$PKG" "$IMAGE" bash test/integration_prereq.sh

echo ">> [3/4] i386 multiarch prereq (behind native Steam)"
podman run --rm -e CONFIGSYS_RESOLVER "$IMAGE" bash test/integration_i386_multiarch.sh

echo ">> [4/4] fastfetch via github .deb (apt deb mode)"
podman run --rm -e CONFIGSYS_RESOLVER "$IMAGE" bash test/integration_fastfetch_deb.sh
