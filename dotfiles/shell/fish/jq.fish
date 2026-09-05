# jq: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (configsys location jq 2>/dev/null)
test -n "$loc"; and test -x "$loc/jq"; and alias jq "$loc/jq"
