# tree-sitter-cli: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (configsys location tree-sitter-cli 2>/dev/null)
test -n "$loc"; and test -x "$loc/tree-sitter"; and alias tree-sitter "$loc/tree-sitter"
