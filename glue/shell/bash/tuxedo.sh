# tuxedo: alias to the tarball-installed binary. The release tarball unpacks into a versioned
# target-triple subdir (tuxedo-<version>-<triple>/tuxedo), so glob for it. No-ops where tuxedo is
# native (brew) and already on PATH.
_tx=$(configsys location tuxedo 2>/dev/null)
if [ -n "$_tx" ]; then
    _txbin=$(ls -1 "$_tx"/tuxedo-*/tuxedo 2>/dev/null | tail -1)
    [ -x "$_txbin" ] && alias tuxedo="$_txbin"
    unset _txbin
fi
unset _tx
