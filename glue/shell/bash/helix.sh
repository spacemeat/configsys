# helix: alias `hx` to the tarball-installed binary. The release tarball unpacks into a
# versioned subdir (helix-<ver>-x86_64-linux/hx) with its runtime/ dir alongside, so glob for
# it. No-ops where hx is native on PATH.
_hx=$(configsys location helix 2>/dev/null)
if [ -n "$_hx" ]; then
    _hxbin=$(ls -1 "$_hx"/helix-*-x86_64-linux/hx 2>/dev/null | tail -1)
    [ -x "$_hxbin" ] && alias hx="$_hxbin"
    unset _hxbin
fi
unset _hx
