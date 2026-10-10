# tuios: alias to the tarball-installed binary wherever configsys unpacked it (the binary sits
# inside the install dir). No-ops where tuios is native on PATH.
_tui=$(cs_loc tuios)
[ -n "$_tui" ] && [ -x "$_tui/tuios" ] && alias tuios="$_tui/tuios"
unset _tui
