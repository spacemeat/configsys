#!/usr/bin/env bash
# Runs INSIDE the void-glibc container as user `tester`. Drives the xbps lifecycle through the real
# configsys entry point and asserts against xbps / the filesystem directly: install -> a REAL hold
# (xbps-pkgdb) -> unhold -> remove, then the Void-specific routing: a renamed package (fish ->
# fish-shell), a `packages:` set (opengl), the nonfree repo (nmap), and a runit service.
set -euo pipefail

PKG="${PKG:-btop}"
say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }
has() { xbps-query "$1" >/dev/null 2>&1; }

. /etc/os-release
say "target: $PRETTY_NAME (ID=$ID) — rolling"

say "bootstrap + inspect (builds .venv, compiles humon)"
bash configsys.sh inspect >/dev/null
bash configsys.sh where curl | grep -q 'on void' || fail "not detected as void"

say "install $PKG"
if has "$PKG"; then fail "$PKG already installed"; fi
bash configsys.sh install "$PKG"
has "$PKG" || fail "$PKG not installed after install"

say "lock $PKG (a real xbps hold)"
bash configsys.sh lock "$PKG"
[ "$(xbps-query -p hold "$PKG")" = yes ] || fail "$PKG not held"
say "unlock $PKG"
bash configsys.sh unlock "$PKG"
[ "$(xbps-query -p hold "$PKG")" != yes ] || fail "$PKG still held"

say "remove $PKG"
bash configsys.sh remove "$PKG"
if has "$PKG"; then fail "$PKG still installed after remove"; fi

say "Void routing: renamed pkg, package set, nonfree repo, runit service"
bash configsys.sh install fish opengl nmap redis-service
has fish-shell || fail "fish -> fish-shell not installed"
has MesaLib-devel && has glu-devel || fail "opengl set not installed"
has void-repo-nonfree && has nmap || fail "nmap (nonfree) not installed"
[ -L /var/service/redis ] || fail "redis runit service not linked"
bash configsys.sh inspect 2>&1 | grep -E "fish|nmap|opengl|redis-service" || true

say "remove the service + the set"
bash configsys.sh remove redis-service opengl
[ ! -e /var/service/redis ] || fail "redis runit service still linked"
if has glu-devel; then fail "opengl set not removed"; fi

printf '\nPASS: xbps cycle for %s + Void routing (rename, set, nonfree, runit)\n' "$PKG"
