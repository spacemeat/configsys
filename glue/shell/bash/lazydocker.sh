# lazydocker: alias to the tarball-installed binary (the only install method). No-ops if not
# managed here.
_ld=$(cs_loc lazydocker)
[ -n "$_ld" ] && [ -x "$_ld/lazydocker" ] && alias lazydocker="$_ld/lazydocker"
unset _ld
