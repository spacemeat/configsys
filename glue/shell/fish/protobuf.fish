# protobuf: add the tarball-installed dir to PATH (no-op where native and already on PATH).
set -l loc (cs_loc protobuf)
test -n "$loc"; and test -x "$loc/bin/protoc"; and fish_add_path -g "$loc/bin"
