# just: alias to the tarball-installed static binary. The musl tarball extracts `just` into the
# managed dir. No-ops where just is native on PATH.
_ju=$(configsys location just 2>/dev/null)
[ -n "$_ju" ] && [ -x "$_ju/just" ] && alias just="$_ju/just"
unset _ju
