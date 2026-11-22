#!/usr/bin/env bash
# Runs INSIDE the Chimera container (test/Containerfile.chimera) as a wheel user escalating through
# doas (Chimera has no sudo). Drives the chimera-apk
# lifecycle through the real configsys entry point, in a --home sandbox, and asserts against apk
# directly: the `user` repository enabled once before the first install (with a note), a main-repo
# package (curl) and a user-repo one (bat) installed non-interactively, their versions read back,
# lock declined (Chimera is rolling — apk has no per-package hold), a later install that leaves
# the enabled repo alone, then everything removed.
set -euo pipefail

say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }
has() { apk info -e "$1" >/dev/null 2>&1; }
ver() { apk list --installed "$1" 2>/dev/null | sed -n "s/^$1-\([0-9][^ ]*\) .*/\1/p"; }

. /etc/os-release
say "target: $PRETTY_NAME (ID=$ID) — rolling"

say "as $(id -un) (uid $(id -u)) — no sudo here, root goes through doas"
if command -v sudo >/dev/null 2>&1; then fail "sudo present — this test is about a doas-only box"; fi
[ "$(id -u)" -ne 0 ] || fail "running as root — the doas path isn't exercised"

say "bootstrap (builds .venv, compiles humon)"
bash configsys.sh inspect >/dev/null
SB="$(mktemp -d)"
cfs() { bash configsys.sh --home "$SB" "$@"; }
cfs where bat | grep -q 'chimera-apk\\bat' || fail "bat doesn't route through chimera-apk"
cfs where python3-pip | grep -q 'pkg python-pip' || fail "python3-pip isn't Chimera's python-pip"

say "before: no curl, no bat, no user repo"
for p in curl bat chimera-repo-user; do if has "$p"; then fail "$p already installed"; fi; done

say "install curl (main) + bat (user repo)"
out="$(cfs install curl bat </dev/null 2>&1)" || { printf '%s\n' "$out"; fail "install failed"; }
printf '%s\n' "$out"
printf '%s\n' "$out" | grep -q "enabling it first" || fail "no note about enabling the user repo"
has chimera-repo-user || fail "user repo not enabled"
has curl && has bat || fail "curl/bat not installed"
grep -qx bat /etc/apk/world || fail "bat not in /etc/apk/world"

say "version read"
for p in curl bat; do
    v="$(ver "$p")"; [ -n "$v" ] || fail "apk reports no $p version"
    cfs versions "$p" | tee /dev/stderr | grep -qF "$v" || fail "configsys doesn't read $p $v"
done

say "lock bat (declined: rolling, no per-package hold)"
out="$(cfs lock bat 2>&1 || true)"; printf '%s\n' "$out"
printf '%s\n' "$out" | grep -q "Chimera is rolling" || fail "lock wasn't declined"

say "a later run: the user repo is left alone (no second note)"
out="$(cfs install fzf </dev/null 2>&1)" || { printf '%s\n' "$out"; fail "fzf install failed"; }
printf '%s\n' "$out"
if printf '%s\n' "$out" | grep -q "enabling it first"; then fail "re-enabled the user repo"; fi
has fzf || fail "fzf not installed"

say "remove bat + curl + fzf"
cfs remove bat curl fzf </dev/null
for p in bat curl fzf; do if has "$p"; then fail "$p still installed after remove"; fi; done

printf '\nPASS: chimera-apk lifecycle (user repo once, curl + bat + fzf, versions, lock declined, remove)\n'
