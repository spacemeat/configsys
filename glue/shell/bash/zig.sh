# Zig: tarball unpacks to zig-linux-*/ under the app dir (no-op when native).
_zg=$(configsys location zig 2>/dev/null)
if [ -n "$_zg" ]; then
    _zb=$(ls -d "$_zg"/zig-linux-*/ 2>/dev/null | tail -1)
    [ -n "$_zb" ] && export PATH="$_zb:$PATH"
    unset _zb
fi
unset _zg
