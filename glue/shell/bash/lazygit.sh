# lazygit: alias to the tarball-installed binary wherever configsys unpacked it (the binary sits
# inside the install dir). No-ops where lazygit is native on PATH.
_lg=$(configsys location lazygit 2>/dev/null)
[ -n "$_lg" ] && [ -x "$_lg/lazygit" ] && alias lazygit="$_lg/lazygit"
unset _lg
