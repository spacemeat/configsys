# zed: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (cs_loc zed)
test -n "$loc"; and test -x "$loc/zed.app/bin/zed"; and alias zed "$loc/zed.app/bin/zed"
