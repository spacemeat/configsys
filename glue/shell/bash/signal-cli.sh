# signal-cli: put the tarball-installed binary on PATH (PATH, not an alias — it's driven from
# scripts and daemons). No-op where signal-cli is native (AUR) on PATH.
_sc=$(configsys location signal-cli 2>/dev/null)
[ -n "$_sc" ] && [ -x "$_sc/signal-cli" ] && export PATH="$_sc:$PATH"
unset _sc
