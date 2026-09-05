# opentofu: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (configsys location opentofu 2>/dev/null)
test -n "$loc"; and test -x "$loc/tofu"; and alias tofu "$loc/tofu"
