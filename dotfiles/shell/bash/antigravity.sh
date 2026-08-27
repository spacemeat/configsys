# antigravity: alias to the tarball-installed launcher (a VS Code fork). The tarball unpacks
# under the managed dir; glob for the `antigravity` executable. No-ops where it's native (AUR).
_ag=$(configsys location antigravity 2>/dev/null)
if [ -n "$_ag" ]; then
    _agbin=$(ls -1 "$_ag"/antigravity "$_ag"/*/antigravity "$_ag"/*/bin/antigravity 2>/dev/null | tail -1)
    [ -x "$_agbin" ] && alias antigravity="$_agbin"
    unset _agbin
fi
unset _ag
