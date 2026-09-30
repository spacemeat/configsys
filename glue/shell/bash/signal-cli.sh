# signal-cli: put the tarball-installed binary on PATH (PATH, not an alias — it's driven from
# scripts and daemons). No-op where signal-cli is native (AUR) on PATH.
_sc=$(cs_loc signal-cli)
[ -n "$_sc" ] && [ -x "$_sc/signal-cli" ] && export PATH="$_sc:$PATH"
unset _sc
