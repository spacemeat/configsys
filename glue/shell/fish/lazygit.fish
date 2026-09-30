# lazygit: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (cs_loc lazygit)
test -n "$loc"; and test -x "$loc/lazygit"; and alias lazygit "$loc/lazygit"
