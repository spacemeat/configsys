# signal-cli: put the tarball-installed binary on PATH (scripts/daemons, so not an alias). No-op where native.
set -l loc (cs_loc signal-cli)
test -n "$loc"; and test -x "$loc/signal-cli"; and fish_add_path -g "$loc"
