#!/usr/bin/env bash
# Runs INSIDE the ubuntu:22.04 container as `tester`. Verifies that configsys
# performs the system prerequisites declared in routes.hu: it DISABLES the
# universe archive component, then installs a universe-only package (btop) via
# configsys and asserts configsys re-enabled universe (repo-component) itself.
set -euo pipefail

PKG="${PKG:-btop}"
say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

say "disable the 'universe' component so the prereq is actually required"
sudo add-apt-repository -y --remove universe
sudo apt-get update -qq

say "confirm $PKG has NO candidate while universe is disabled"
policy=$(apt-cache policy "$PKG")
if grep -q 'Candidate: [0-9]' <<<"$policy"; then
    fail "$PKG still installable with universe disabled — test can't prove the prereq"
fi

say "install $PKG via configsys (must re-enable universe first)"
bash bootstrap.sh install "$PKG"

say "assert universe is now enabled"
grep -Rqs -E '^(deb|Components:).*universe' /etc/apt/sources.list /etc/apt/sources.list.d/ \
    || fail "universe was not re-enabled by configsys"

say "assert $PKG is installed"
dpkg -s "$PKG" >/dev/null 2>&1 || fail "$PKG not installed after prereq+install"

printf '\nPASS: configsys enabled the required repo-component (universe) and installed %s\n' "$PKG"
