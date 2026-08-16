# jq: alias to the tarball-installed static binary (upstream ships a raw binary, no archive).
# No-ops where jq is native on PATH.
_jq=$(configsys location jq 2>/dev/null)
[ -n "$_jq" ] && [ -x "$_jq/jq" ] && alias jq="$_jq/jq"
unset _jq
