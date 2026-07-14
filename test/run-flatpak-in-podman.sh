#!/usr/bin/env bash
# Gated (slow, networked) flatpak integration. Builds the shared test image and runs
# the flatpak --user lifecycle inside a throwaway container with /dev/fuse. Pulls a
# runtime from flathub, so it is intentionally NOT part of run-in-podman.sh.
#
# Usage: bash test/run-flatpak-in-podman.sh [APPID]
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"
APP="${1:-com.github.tchx84.Flatseal}"
IMAGE="configsys-test:latest"

command -v podman >/dev/null 2>&1 || { echo "podman not found" >&2; exit 127; }

echo ">> building $IMAGE (context: $repo)"
podman build -q -t "$IMAGE" -f "$here/Containerfile" "$repo"

echo ">> flatpak --user lifecycle (APP=$APP, /dev/fuse)"
# flatpak needs a D-Bus session bus; dbus-run-session provides a throwaway one.
podman run --rm --device /dev/fuse --security-opt seccomp=unconfined \
    -e "APP=$APP" "$IMAGE" dbus-run-session -- bash test/integration_flatpak.sh
