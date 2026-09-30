# opentofu: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (cs_loc opentofu)
test -n "$loc"; and test -x "$loc/tofu"; and alias tofu "$loc/tofu"
