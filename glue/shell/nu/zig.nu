# zig: prepend the tarball's versioned subdir to PATH. No-op where native on PATH.
let zig_loc = (cs-loc zig)
if ($zig_loc != "") { cs-prepend (cs-glob1 $"($zig_loc)/zig-linux-*") }
