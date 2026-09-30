# Arduino IDE: alias to the appImage wherever configsys installed it (honors your layout/scope).
_ar=$(cs_loc arduino)
[ -x "$_ar" ] && alias arduino="$_ar"
unset _ar
