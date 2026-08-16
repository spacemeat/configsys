# xh: alias to the tarball-installed binary (default over cargo). The tarball unpacks into a
# versioned subdir; glob for it. No-ops when installed via cargo (already on PATH).
_xh=$(configsys location xh 2>/dev/null)
if [ -n "$_xh" ]; then
    _xhbin=$(ls -1 "$_xh"/xh-*/xh "$_xh"/xh 2>/dev/null | tail -1)
    [ -x "$_xhbin" ] && alias xh="$_xhbin"
    unset _xhbin
fi
unset _xh
