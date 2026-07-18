#!/usr/bin/env bash
# Runs INSIDE the ubuntu:22.04 container as user `tester`. Exercises the apt family's
# i386 `foreign-arch` prereq (the new capability behind native Steam) end to end on
# real apt/dpkg, using a tiny i386 package instead of Steam's heavy 32-bit stack.
set -euo pipefail

say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

TEST_PKG="zlib1g:i386"     # tiny, in Ubuntu main — no multiverse needed

say "precondition: i386 multiarch NOT enabled"
if dpkg --print-foreign-architectures | grep -qx i386; then fail "i386 already enabled"; fi
sudo apt-get update -qq

say "build .venv (bootstrap)"
bash configsys.sh inspect >/dev/null 2>&1 || true

say "install $TEST_PKG via the apt family (foreign-arch enables i386 first)"
.venv/bin/python - "$TEST_PKG" <<'PY'
import sys
from configsys.families.apt import Apt
from configsys.runner import Runner
from configsys.componentObj import ResolvedComponent
rc = ResolvedComponent(key='apt\\t', family='apt', comp='t',
                       fields={'name': sys.argv[1], 'foreign-arch': 'i386'})
sys.exit(0 if Apt(Runner()).install(rc).ok else 1)
PY

say "assert i386 got enabled and the i386 package installed"
dpkg --print-foreign-architectures | grep -qx i386 || fail "i386 not enabled by the prereq"
dpkg -l zlib1g:i386 2>/dev/null | grep -q '^ii' || fail "$TEST_PKG not installed"
echo "  i386 enabled; $TEST_PKG $(dpkg-query -W -f='${Version}' zlib1g:i386)"

say "idempotence: a second run is a no-op (no re-add)"
before=$(dpkg --print-foreign-architectures)
.venv/bin/python - "$TEST_PKG" <<'PY'
import sys
from configsys.families.apt import Apt
from configsys.runner import Runner
from configsys.componentObj import ResolvedComponent
rc = ResolvedComponent(key='apt\\t', family='apt', comp='t',
                       fields={'name': sys.argv[1], 'foreign-arch': 'i386'})
Apt(Runner()).install(rc)
PY
[ "$(dpkg --print-foreign-architectures)" = "$before" ] || fail "arch list changed on re-run"

printf '\nPASS: apt i386 foreign-arch prereq (the mechanism behind native Steam on Pop)\n'
