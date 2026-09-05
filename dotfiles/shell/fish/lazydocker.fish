# lazydocker: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (configsys location lazydocker 2>/dev/null)
test -n "$loc"; and test -x "$loc/lazydocker"; and alias lazydocker "$loc/lazydocker"
