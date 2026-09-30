# opentofu: alias `tofu` to the tarball-installed binary. No-ops where not tarball-installed.
_tofu=$(cs_loc opentofu)
[ -n "$_tofu" ] && [ -x "$_tofu/tofu" ] && alias tofu="$_tofu/tofu"
unset _tofu
