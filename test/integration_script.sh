#!/usr/bin/env bash
# Runs INSIDE a container as `tester`. Validates the `script` driver end to end with SDKMAN:
# configsys installs it via the declared install-cmd (curl | bash), the declared version-cmd
# reads a version, and the declared uninstall-cmd removes it cleanly. Needs network. Non-zero on
# mismatch.
set -euo pipefail

say()  { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

. /etc/os-release
say "target: $PRETTY_NAME"

sudo apt-get update -qq >/dev/null 2>&1
sudo apt-get install -y -qq zip unzip >/dev/null 2>&1     # the sdkman installer needs zip/unzip
printf '{ configs: user }\n' > "$HOME/configsys.hu"

say "configsys install sdkman (script driver: curl | bash)"
bash configsys.sh install sdkman
[ -s "$HOME/.sdkman/bin/sdkman-init.sh" ] || fail "sdkman not installed at ~/.sdkman"
echo "  installed at ~/.sdkman"

say "the declared version-cmd yields a version (what get_version parses)"
# run it exactly as the driver does — a fresh `bash -c` (NOT the test's set -u shell, which
# sdkman's own init script isn't written for)
V=$(bash -c 'source "$HOME/.sdkman/bin/sdkman-init.sh" && sdk version' 2>/dev/null \
    | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
[ -n "$V" ] || fail "declared version-cmd produced no version"
echo "  sdk version -> $V"

say "configsys remove sdkman (declared uninstall-cmd: rm -rf ~/.sdkman)"
bash configsys.sh remove sdkman
[ -d "$HOME/.sdkman" ] && fail "~/.sdkman still present after remove"
echo "  ~/.sdkman removed cleanly"

printf '\nPASS: script driver end-to-end (sdkman) on %s\n' "$PRETTY_NAME"
