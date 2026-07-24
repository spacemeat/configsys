#!/usr/bin/env bash
# Gated (slow, networked) language-toolchain + module-driver integration. Installs real
# toolchains (rust/node/go/ruby) and exercises the npm/gem/go-install drivers inside a throwaway
# container, asserting userland module installs and real version parsing. Nothing touches the host.
#
# Usage: bash test/run-langs-in-podman.sh [distro ...]   (default: noble)
#   distro ∈ noble fedora arch opensuse   — Containerfile.<distro> (noble -> Containerfile.noble)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"

command -v podman >/dev/null 2>&1 || { echo "podman not found" >&2; exit 127; }

for distro in "${@:-noble}"; do
    file="$here/Containerfile.$distro"
    [ "$distro" = noble ] && file="$here/Containerfile.noble"
    [ -f "$file" ] || { echo "no $file" >&2; exit 2; }
    img="configsys-test:langs-$distro"
    echo ">> building $img ($distro)"
    podman build -q -t "$img" -f "$file" "$repo"
    echo ">> language toolchains + module drivers on $distro"
    podman run --rm "$img" bash test/integration_langs.sh
done
