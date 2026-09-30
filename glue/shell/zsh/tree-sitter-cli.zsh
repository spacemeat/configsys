# tree-sitter-cli: alias `tree-sitter` to the tarball-installed binary (only used if the tarball
# binding is pinned -- the default cargo build already lands on PATH in ~/.cargo/bin). No-ops
# otherwise.
_ts=$(cs_loc tree-sitter-cli)
[ -n "$_ts" ] && [ -x "$_ts/tree-sitter" ] && alias tree-sitter="$_ts/tree-sitter"
unset _ts
