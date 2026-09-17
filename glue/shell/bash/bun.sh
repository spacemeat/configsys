# Bun: tarball install dir (zip -> bun-linux-*/ subdir; no-op when native) + global bin.
_bn=$(configsys location bun 2>/dev/null)
if [ -n "$_bn" ]; then
    _bb=$(ls -d "$_bn"/bun-linux-*/ 2>/dev/null | tail -1)
    [ -n "$_bb" ] && export PATH="$_bb:$PATH"
    unset _bb
fi
unset _bn
export BUN_INSTALL="$HOME/.bun"
[ -d "$BUN_INSTALL/bin" ] && export PATH="$PATH:$BUN_INSTALL/bin"
