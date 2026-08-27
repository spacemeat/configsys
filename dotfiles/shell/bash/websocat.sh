# websocat: alias to the tarball-installed single binary (default over cargo). No-ops when
# installed via cargo (already on PATH).
_ws=$(configsys location websocat 2>/dev/null)
[ -n "$_ws" ] && [ -x "$_ws/websocat" ] && alias websocat="$_ws/websocat"
unset _ws
