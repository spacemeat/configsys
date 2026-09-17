# fossil: alias to the tarball-installed static binary (openSUSE fallback -- no distro pkg).
# No-ops where fossil is native on PATH.
_fo=$(configsys location fossil 2>/dev/null)
[ -n "$_fo" ] && [ -x "$_fo/fossil" ] && alias fossil="$_fo/fossil"
unset _fo
