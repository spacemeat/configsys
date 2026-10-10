# cliamp: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (cs_loc cliamp)
test -n "$loc"; and test -x "$loc/cliamp"; and alias cliamp "$loc/cliamp"
