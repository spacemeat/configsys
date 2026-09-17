# rar: add the tarball-installed dir to PATH (no-op where native and already on PATH).
set -l loc (configsys location rar 2>/dev/null)
test -n "$loc"; and test -x "$loc/rar/rar"; and fish_add_path -g "$loc/rar"
