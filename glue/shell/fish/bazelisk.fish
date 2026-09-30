# bazelisk: alias to the tarball-installed launcher; also expose it as `bazel`. No-ops where native.
set -l loc (cs_loc bazelisk)
if test -n "$loc"; and test -x "$loc/bazelisk"
    alias bazelisk "$loc/bazelisk"
    alias bazel "$loc/bazelisk"
end
