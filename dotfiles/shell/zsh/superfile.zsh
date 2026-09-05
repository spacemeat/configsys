# superfile: alias `spf` to the tarball-installed binary. The release tarball unpacks into a
# versioned subdir (dist/superfile-linux-<version>-amd64/spf), so glob for it. No-ops where
# superfile is native (pacman/brew) and already on PATH.
_sf=$(configsys location superfile 2>/dev/null)
if [ -n "$_sf" ]; then
    _spfbin=$(ls -1 "$_sf"/dist/superfile-linux-*/spf 2>/dev/null | tail -1)
    [ -x "$_spfbin" ] && alias spf="$_spfbin"
    unset _spfbin
fi
unset _sf
