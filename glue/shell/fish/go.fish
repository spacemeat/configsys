# Go: tarball toolchain (SDK dir; no-op when native) + `go install` binaries (GOBIN) on PATH.
set -l loc (cs_loc go)
test -n "$loc"; and test -x "$loc/bin/go"; and fish_add_path -g "$loc/bin"
set -l gobin $GOBIN
test -z "$gobin"; and set gobin "$HOME/go/bin"
fish_add_path -ga "$gobin"
