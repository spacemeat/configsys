# yazi: alias to the tarball-installed binary. The release zip unpacks into a stable
# target-triple subdir (yazi-<triple>/yazi), so glob for it. No-ops where yazi is native
# (deb/pacman/brew) and already on PATH.
_yz=$(configsys location yazi 2>/dev/null)
if [ -n "$_yz" ]; then
    _yzbin=$(ls -1 "$_yz"/yazi-*-unknown-linux-gnu/yazi 2>/dev/null | tail -1)
    [ -x "$_yzbin" ] && alias yazi="$_yzbin"
    unset _yzbin
fi
unset _yz
