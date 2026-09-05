# fossil: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (configsys location fossil 2>/dev/null)
test -n "$loc"; and test -x "$loc/fossil"; and alias fossil "$loc/fossil"
