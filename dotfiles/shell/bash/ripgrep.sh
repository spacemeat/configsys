# ripgrep: alias `rg` to the tarball-installed binary. The prebuilt musl tarball unpacks into a
# versioned subdir (ripgrep-<ver>-x86_64-unknown-linux-musl/rg), so glob for it. No-ops where
# rg is native on PATH.
_rg=$(configsys location ripgrep 2>/dev/null)
if [ -n "$_rg" ]; then
    _rgbin=$(ls -1 "$_rg"/ripgrep-*/rg 2>/dev/null | tail -1)
    [ -x "$_rgbin" ] && alias rg="$_rgbin"
    unset _rgbin
fi
unset _rg
