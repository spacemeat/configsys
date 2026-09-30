# v: add the tarball-installed dir to PATH (no-op where native and already on PATH).
set -l loc (cs_loc v)
test -n "$loc"; and test -x "$loc/v/v"; and fish_add_path -g "$loc/v"
