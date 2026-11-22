#!/usr/bin/env bash
# Build a throwaway Chimera Linux image and run the chimera-apk lifecycle inside it, as an ordinary
# user escalating through doas (Chimera ships no sudo). Nothing touches the host.
#
# Usage: bash test/run-chimera-in-podman.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"
IMAGE="configsys-test:chimera"

command -v podman >/dev/null 2>&1 || { echo "podman not found" >&2; exit 127; }

echo ">> building $IMAGE (context: $repo)"
podman build -q -t "$IMAGE" -f "$here/Containerfile.chimera" "$repo"

echo ">> chimera-apk lifecycle"
podman run --rm "$IMAGE" bash test/integration_chimera.sh
