# btop: alias to the tarball-installed binary. The prebuilt musl tarball unpacks a top-level
# btop/ dir (btop/bin/btop). No-ops where btop is native on PATH.
_bt=$(configsys location btop 2>/dev/null)
if [ -n "$_bt" ]; then
    _btbin=$(ls -1 "$_bt"/btop/bin/btop "$_bt"/bin/btop 2>/dev/null | tail -1)
    [ -x "$_btbin" ] && alias btop="$_btbin"
    unset _btbin
fi
unset _bt
