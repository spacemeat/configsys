# just: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (configsys location just 2>/dev/null)
test -n "$loc"; and test -x "$loc/just"; and alias just "$loc/just"
