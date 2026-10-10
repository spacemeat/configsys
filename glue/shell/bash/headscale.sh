# headscale: alias to the tarball-installed binary wherever configsys unpacked it (the binary sits
# inside the install dir). No-ops where headscale is native on PATH.
_hea=$(cs_loc headscale)
[ -n "$_hea" ] && [ -x "$_hea/headscale" ] && alias headscale="$_hea/headscale"
unset _hea
