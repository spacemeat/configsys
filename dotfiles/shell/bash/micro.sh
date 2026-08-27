# micro: alias to the tarball-installed binary. The release tarball unpacks into a versioned
# subdir (micro-<ver>/micro), so glob for it. No-ops where micro is native on PATH.
_mi=$(configsys location micro 2>/dev/null)
if [ -n "$_mi" ]; then
    _mibin=$(ls -1 "$_mi"/micro-*/micro 2>/dev/null | tail -1)
    [ -x "$_mibin" ] && alias micro="$_mibin"
    unset _mibin
fi
unset _mi
