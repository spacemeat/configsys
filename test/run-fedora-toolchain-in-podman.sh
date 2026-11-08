#!/usr/bin/env bash
# Gated (slow, networked) Fedora toolchain integration: installs versioned gcc/clang
# compat packages through configsys in a throwaway fedora:41 container and asserts
# the Fedora acquisition model (versioned binaries, no update-alternatives).
#
# Usage: bash test/run-fedora-toolchain-in-podman.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"

command -v podman >/dev/null 2>&1 || { echo "podman not found" >&2; exit 127; }

# Exercise the live Fedora releases: the routable versions differ per release
# (43 -> gcc-14, 44/45 -> gcc-15), driven by the release-bounded gcc-NN bindings.
for rel in "${@:-43 44 45}"; do
    img="configsys-test:fedora$rel"
    echo ">> building $img (fedora:$rel)"
    podman build -q -t "$img" --build-arg "FEDORA=$rel" -f "$here/Containerfile.fedora" "$repo"
    echo ">> Fedora $rel versioned toolchain"
    podman run --rm "$img" bash test/integration_fedora_toolchain.sh
done
