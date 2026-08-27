# ghostty: alias to the appImage wherever configsys installed it. No-ops where ghostty is
# native (arch) on PATH (location then reports no managed path and this simply skips).
_gh=$(configsys location ghostty 2>/dev/null)
[ -x "$_gh" ] && alias ghostty="$_gh"
unset _gh
