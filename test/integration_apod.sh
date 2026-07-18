#!/usr/bin/env bash
# Runs INSIDE the container as user `tester`. Drives a real apod install through
# the configsys entry point and asserts the end state, independent of how pipx was
# acquired (apt on modern OSs, pip --user bootstrap on older ones). Needs network
# (PyPI + possibly the apt pipx package). Exits non-zero on any mismatch.
set -euo pipefail

say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

. /etc/os-release
say "target: $PRETTY_NAME (VERSION_ID=$VERSION_ID)"

say "refresh apt lists"
sudo apt-get update -qq

say "bootstrap + inspect"
bash configsys.sh inspect

say "precondition: termapod NOT installed"
if [ -x "$HOME/.local/bin/termapod" ]; then fail "termapod already present"; fi

say "install apod via configsys (pipx; bootstraps pipx per OS version)"
bash configsys.sh install apod

say "termapod binary landed in ~/.local/bin"
[ -x "$HOME/.local/bin/termapod" ] || fail "~/.local/bin/termapod missing"

say "pipx tracks termapod"
python3 -m pipx list --json | grep -q '"termapod"' || fail "pipx does not list termapod"

say "startup dotfile linked"
[ -e "$HOME/.bash.d/apod.sh" ] || fail "~/.bash.d/apod.sh not linked"

say "remove apod via configsys"
bash configsys.sh remove apod
if [ -x "$HOME/.local/bin/termapod" ]; then fail "termapod still present after remove"; fi

printf '\nPASS: apod install -> pipx (bootstrapped as needed) -> remove on %s\n' "$VERSION_ID"
