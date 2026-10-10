# herdr: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (cs_loc herdr)
test -n "$loc"; and test -x "$loc/herdr"; and alias herdr "$loc/herdr"
