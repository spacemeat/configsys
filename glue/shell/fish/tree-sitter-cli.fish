# tree-sitter-cli: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (cs_loc tree-sitter-cli)
test -n "$loc"; and test -x "$loc/tree-sitter"; and alias tree-sitter "$loc/tree-sitter"
