# elm: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (cs_loc elm)
test -n "$loc"; and test -x "$loc/elm"; and alias elm "$loc/elm"
