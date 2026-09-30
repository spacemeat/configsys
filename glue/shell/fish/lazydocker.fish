# lazydocker: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (cs_loc lazydocker)
test -n "$loc"; and test -x "$loc/lazydocker"; and alias lazydocker "$loc/lazydocker"
