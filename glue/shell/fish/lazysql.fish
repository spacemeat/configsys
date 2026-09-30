# lazysql: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (cs_loc lazysql)
test -n "$loc"; and test -x "$loc/lazysql"; and alias lazysql "$loc/lazysql"
