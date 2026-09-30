# websocat: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (cs_loc websocat)
test -n "$loc"; and test -x "$loc/websocat"; and alias websocat "$loc/websocat"
