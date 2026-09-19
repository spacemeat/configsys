# julia: prepend the tarball's versioned subdir to PATH. No-op where native on PATH.
let julia_loc = (cs-loc julia)
if ($julia_loc != "") { cs-prepend (cs-glob1 $"($julia_loc)/julia-*/bin") }
