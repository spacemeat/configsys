# k9s: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (cs_loc k9s)
test -n "$loc"; and test -x "$loc/k9s"; and alias k9s "$loc/k9s"
