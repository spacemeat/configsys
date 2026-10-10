# herdr: alias to the tarball-installed binary wherever configsys unpacked it (the binary sits
# inside the install dir). No-ops where herdr is native on PATH.
_her=$(cs_loc herdr)
[ -n "$_her" ] && [ -x "$_her/herdr" ] && alias herdr="$_her/herdr"
unset _her
