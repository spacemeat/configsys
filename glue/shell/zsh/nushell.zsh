# nushell: put the tarball-installed `nu` on PATH (the release tarball unpacks into a versioned
# target-triple subdir, nu-<ver>-x86_64-unknown-linux-{gnu,musl}/nu) so `nu` execs AND `which nu`
# detects it. It MUST be on PATH, not an alias — configsys's shell detection is `which nu`, and an
# alias is invisible to it (so an aliased nu never gets its own glue). No-op where nu is native on PATH.
_nu=$(configsys location nushell 2>/dev/null)
if [ -n "$_nu" ]; then
    _nubin=$(ls -1 "$_nu"/nu-*-x86_64-unknown-linux-*/nu 2>/dev/null | tail -1)
    [ -x "$_nubin" ] && export PATH="$(dirname "$_nubin"):$PATH"
    unset _nubin
fi
unset _nu
