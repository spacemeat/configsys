#!/usr/bin/env bash
# Runs INSIDE the ubuntu:22.04 container as `tester`. Exercises the Flatpak family
# end-to-end in the unprivileged --user installation: install -> list -> mask(lock)
# -> unmask -> uninstall of a tiny flathub app. Asserts against `flatpak` directly.
# Networked + pulls a runtime, so this is a gated (slow) test, separate from the
# fast apt cycle. We only install/remove (never launch), so no bwrap/dbus runtime.
set -euo pipefail

APP="${APP:-com.github.tchx84.Flatseal}"
say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/xdgrt-$(id -u)}"
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"

# flatpak connects to the system D-Bus even for --user installs; start one.
# (bwrap proc-mount warnings during post-install triggers are non-fatal here.)
sudo mkdir -p /run/dbus
sudo dbus-daemon --system --fork 2>/dev/null || sudo service dbus start 2>/dev/null || true

PY=".venv/bin/python"
drive() { "$PY" test/flatpak_family_drive.py "$@"; }

say "bootstrap (build .venv + humon)"
bash configsys.sh inspect >/dev/null 2>&1 || bash configsys.sh inspect

say "add flathub (user) and confirm $APP exists"
flatpak remote-add --user --if-not-exists flathub \
    https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak remote-info --user flathub "$APP" >/dev/null 2>&1 \
    || fail "$APP not found on flathub (set APP=<appid>)"

say "precondition: $APP not installed (--user)"
[ -z "$(drive version "$APP")" ] || fail "$APP already installed"

say "install $APP via the Flatpak family"
drive install "$APP"
grep -qx "$APP" <<<"$(flatpak list --user --columns=application)" \
    || fail "$APP not in --user list after install"
echo "installed version: $(drive version "$APP")"

say "lock (mask) $APP"
drive lock "$APP"
[ "$(drive locked "$APP")" = yes ] || fail "$APP not masked after lock"

say "unlock (unmask) $APP"
drive unlock "$APP"
[ "$(drive locked "$APP")" = no ] || fail "$APP still masked after unlock"

say "uninstall $APP"
drive uninstall "$APP"
if grep -qx "$APP" <<<"$(flatpak list --user --columns=application)"; then
    fail "$APP still installed after uninstall"
fi

printf '\nPASS: full flatpak --user install -> lock -> unlock -> uninstall for %s\n' "$APP"
