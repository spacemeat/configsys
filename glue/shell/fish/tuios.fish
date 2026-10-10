# tuios: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (cs_loc tuios)
test -n "$loc"; and test -x "$loc/tuios"; and alias tuios "$loc/tuios"
