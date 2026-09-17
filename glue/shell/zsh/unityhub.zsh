# unityhub: alias to the AppImage wherever configsys installed it. No-ops if not the appImage.
_uh=$(configsys location unityhub 2>/dev/null)
[ -x "$_uh" ] && alias unityhub="$_uh"
unset _uh
