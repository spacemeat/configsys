#!/usr/bin/env bash
# Name-existence sweep: verify every native package configsys maps to still EXISTS in its target
# repos across apt/dnf/pacman/zypper/apk (catches renames/removals — redis→valkey, a dropped
# package, a -dev suffix change). Read-only queries in throwaway containers; nothing is installed.
# See docs/name-sweep-test.md.
#
# Usage: bash test/run-name-sweep-in-podman.sh [manager[,manager...]]   # default: all five
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"
py="$repo/.venv/bin/python"; [ -x "$py" ] || py=python3

command -v podman >/dev/null 2>&1 || { echo "podman not found" >&2; exit 127; }

exec "$py" "$repo/tools/namesweep.py" --sweep ${1:+--only "$1"}
