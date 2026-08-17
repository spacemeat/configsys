# grpcurl: add the tarball-installed grpcurl (flat binary in the install dir) to PATH.
_gc=$(configsys location grpcurl 2>/dev/null)
[ -n "$_gc" ] && [ -x "$_gc/grpcurl" ] && case ":$PATH:" in *":$_gc:"*) ;; *) PATH="$PATH:$_gc"; export PATH ;; esac
unset _gc
