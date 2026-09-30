# bazelisk: alias to the tarball-installed launcher wherever configsys unpacked it. Also expose
# it as `bazel` (bazelisk is a drop-in Bazel launcher). No-ops where bazelisk is native on PATH.
_bz=$(cs_loc bazelisk)
if [ -n "$_bz" ] && [ -x "$_bz/bazelisk" ]; then
    alias bazelisk="$_bz/bazelisk"
    alias bazel="$_bz/bazelisk"
fi
unset _bz
