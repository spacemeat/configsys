# lazydocker: alias to the tarball-installed binary (the only install method). No-ops if not
# managed here.
_ld=$(configsys location lazydocker 2>/dev/null)
[ -n "$_ld" ] && [ -x "$_ld/lazydocker" ] && alias lazydocker="$_ld/lazydocker"
unset _ld
