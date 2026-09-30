# just: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (cs_loc just)
test -n "$loc"; and test -x "$loc/just"; and alias just "$loc/just"
