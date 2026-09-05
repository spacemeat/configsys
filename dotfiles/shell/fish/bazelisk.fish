# bazelisk: alias to the tarball-installed launcher; also expose it as `bazel`. No-ops where native.
set -l loc (configsys location bazelisk 2>/dev/null)
if test -n "$loc"; and test -x "$loc/bazelisk"
    alias bazelisk "$loc/bazelisk"
    alias bazel "$loc/bazelisk"
end
