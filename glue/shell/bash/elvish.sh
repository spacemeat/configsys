# elvish: put the tarball-installed elvish on PATH (the dl.elv.sh tarball is a flat `elvish` binary
# in the managed dir) so `elvish` execs AND `which elvish` detects it. No-op where native on PATH.
_el=$(cs_loc elvish)
[ -n "$_el" ] && [ -x "$_el/elvish" ] && export PATH="$_el:$PATH"
unset _el
