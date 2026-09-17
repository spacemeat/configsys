# lazygit: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (configsys location lazygit 2>/dev/null)
test -n "$loc"; and test -x "$loc/lazygit"; and alias lazygit "$loc/lazygit"
