# kubectl: add the tarball-installed static binary to PATH + enable completion. No-op where native.
set -l loc (configsys location kubectl 2>/dev/null)
test -n "$loc"; and test -x "$loc/kubectl"; and fish_add_path -ga "$loc"
command -v kubectl >/dev/null 2>&1; and kubectl completion fish 2>/dev/null | source
