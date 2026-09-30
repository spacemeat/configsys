# unityhub: alias to the AppImage wherever configsys installed it. No-ops if not the appImage.
_uh=$(cs_loc unityhub)
[ -x "$_uh" ] && alias unityhub="$_uh"
unset _uh
