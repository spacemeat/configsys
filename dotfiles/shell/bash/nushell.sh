# nushell: alias `nu` to the tarball-installed binary. The release tarball unpacks into a
# versioned target-triple subdir (nu-<ver>-x86_64-unknown-linux-{gnu,musl}/nu), so glob for it.
# No-ops where nu is native (arch/brew) on PATH.
_nu=$(configsys location nushell 2>/dev/null)
if [ -n "$_nu" ]; then
    _nubin=$(ls -1 "$_nu"/nu-*-x86_64-unknown-linux-*/nu 2>/dev/null | tail -1)
    [ -x "$_nubin" ] && alias nu="$_nubin"
    unset _nubin
fi
unset _nu
