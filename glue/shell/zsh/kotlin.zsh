# kotlin: add the tarball-installed Kotlin compiler's bin to PATH (unpacks into kotlinc/bin).
# No-op where kotlin is native (pacman/brew) and already on PATH.
_kt=$(configsys location kotlin 2>/dev/null)
if [ -n "$_kt" ]; then
    _ktbin="$_kt/kotlinc/bin"
    [ -d "$_ktbin" ] && case ":$PATH:" in *":$_ktbin:"*) ;; *) PATH="$PATH:$_ktbin"; export PATH ;; esac
    unset _ktbin
fi
unset _kt
