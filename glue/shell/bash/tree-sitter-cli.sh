# tree-sitter-cli: alias `tree-sitter` to the tarball-installed binary (only used if the tarball
# binding is pinned -- the default cargo build already lands on PATH in ~/.cargo/bin). No-ops
# otherwise.
_ts=$(configsys location tree-sitter-cli 2>/dev/null)
[ -n "$_ts" ] && [ -x "$_ts/tree-sitter" ] && alias tree-sitter="$_ts/tree-sitter"
unset _ts
