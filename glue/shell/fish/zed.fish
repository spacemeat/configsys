# zed: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (configsys location zed 2>/dev/null)
test -n "$loc"; and test -x "$loc/zed.app/bin/zed"; and alias zed "$loc/zed.app/bin/zed"
