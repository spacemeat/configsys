# rar: put the tarball-installed rar/unrar binaries on PATH (the rarlab tar unpacks a rar/ dir
# under the managed install dir). No-ops where rar is native (deb multiverse / AUR) on PATH.
_rr=$(configsys location rar 2>/dev/null)
[ -n "$_rr" ] && [ -x "$_rr/rar/rar" ] && export PATH="$_rr/rar:$PATH"
unset _rr
