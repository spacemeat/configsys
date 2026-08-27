# zed: alias to the tarball-installed binary. The release tarball unpacks a zed.app bundle
# (zed.app/bin/zed). No-ops where zed is native (arch)/script-installed (~/.local/bin) on PATH.
_zd=$(configsys location zed 2>/dev/null)
[ -n "$_zd" ] && [ -x "$_zd/zed.app/bin/zed" ] && alias zed="$_zd/zed.app/bin/zed"
unset _zd
