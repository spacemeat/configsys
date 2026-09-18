# zig: prepend the tarball's versioned subdir to PATH. No-op where native on PATH.
use path
var loc = (cs-loc zig)
if (not-eq $loc '') {
  for d [$loc/zig-linux-*[nomatch-ok]] { if (and (path:is-dir $d) (not (has-value $paths $d))) { set paths = [$d $@paths]; break } }
}
