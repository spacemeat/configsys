# jetbrains-toolbox: alias to the tarball-installed launcher. The tarball unpacks into a
# versioned subdir (jetbrains-toolbox-<ver>/jetbrains-toolbox), so glob for it.
_jt=$(configsys location jetbrains-toolbox 2>/dev/null)
if [ -n "$_jt" ]; then
    _jtbin=$(ls -1 "$_jt"/jetbrains-toolbox-*/jetbrains-toolbox "$_jt"/jetbrains-toolbox 2>/dev/null | tail -1)
    [ -x "$_jtbin" ] && alias jetbrains-toolbox="$_jtbin"
    unset _jtbin
fi
unset _jt
