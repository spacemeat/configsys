# zellij: alias to the tarball-installed binary (flat — the musl tarball unpacks `zellij` at the
# install root). No-ops where zellij is native (pacman/brew) and already on PATH.
_zj=$(configsys location zellij 2>/dev/null)
if [ -n "$_zj" ] && [ -x "$_zj/zellij" ]; then
    alias zellij="$_zj/zellij"
fi
unset _zj
