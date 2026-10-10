# headscale: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (cs_loc headscale)
test -n "$loc"; and test -x "$loc/headscale"; and alias headscale "$loc/headscale"
