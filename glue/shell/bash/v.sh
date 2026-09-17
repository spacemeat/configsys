# V: zip unpacks to v/ under the app dir (no-op when native/aur).
_v=$(configsys location v 2>/dev/null)
[ -n "$_v" ] && [ -x "$_v/v/v" ] && export PATH="$_v/v:$PATH"
unset _v
