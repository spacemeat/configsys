# opentofu: alias `tofu` to the tarball-installed binary. No-ops where not tarball-installed.
_tofu=$(configsys location opentofu 2>/dev/null)
[ -n "$_tofu" ] && [ -x "$_tofu/tofu" ] && alias tofu="$_tofu/tofu"
unset _tofu
