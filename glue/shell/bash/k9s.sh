# k9s: alias to the tarball-installed binary. The release tarball extracts `k9s` into the
# managed dir. No-ops where k9s is native (arch/brew) on PATH.
_k9=$(configsys location k9s 2>/dev/null)
[ -n "$_k9" ] && [ -x "$_k9/k9s" ] && alias k9s="$_k9/k9s"
unset _k9
