# Arduino IDE: alias to the appImage wherever configsys installed it (honors your layout/scope).
_ar=$(configsys location arduino 2>/dev/null)
[ -x "$_ar" ] && alias arduino="$_ar"
unset _ar
