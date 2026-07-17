#!/usr/bin/env bash
# Gated (slow, networked) apod integration across BOTH OS-version paths:
#   jammy (22.04) -> no apt pipx  -> pip --user bootstrap  (ubuntu@<23.04 variant)
#   noble (24.04) -> apt pipx     -> apt\pipx              (base block, PEP 668-safe)
# Pulls termapod from PyPI (and pipx on noble), so it is NOT part of run-in-podman.sh.
#
# Usage: bash test/run-apod-in-podman.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"

command -v podman >/dev/null 2>&1 || { echo "podman not found" >&2; exit 127; }

echo ">> [1/2] jammy (22.04) — pip --user bootstrap path"
podman build -q -t configsys-test:jammy -f "$here/Containerfile" "$repo"
podman run --rm configsys-test:jammy bash test/integration_apod.sh

echo ">> [2/2] noble (24.04) — apt pipx path"
podman build -q -t configsys-test:noble -f "$here/Containerfile.noble" "$repo"
podman run --rm configsys-test:noble bash test/integration_apod.sh
