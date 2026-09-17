# v: add the tarball-installed dir to PATH (no-op where native and already on PATH).
set -l loc (configsys location v 2>/dev/null)
test -n "$loc"; and test -x "$loc/v/v"; and fish_add_path -g "$loc/v"
