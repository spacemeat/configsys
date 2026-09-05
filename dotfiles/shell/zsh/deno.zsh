# Deno: tarball install dir (no-op when native) + `deno install` global scripts.
_dn=$(configsys location deno 2>/dev/null)
[ -n "$_dn" ] && [ -x "$_dn/deno" ] && export PATH="$_dn:$PATH"
unset _dn
[ -d "$HOME/.deno/bin" ] && export PATH="$PATH:$HOME/.deno/bin"
