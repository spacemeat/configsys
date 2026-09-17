# grpcurl: add the tarball-installed dir to PATH (no-op where native and already on PATH).
set -l loc (configsys location grpcurl 2>/dev/null)
test -n "$loc"; and test -x "$loc/grpcurl"; and fish_add_path -g "$loc"
