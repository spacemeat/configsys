# fossil: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (cs_loc fossil)
test -n "$loc"; and test -x "$loc/fossil"; and alias fossil "$loc/fossil"
