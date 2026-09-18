# julia: prepend the tarball's versioned subdir to PATH. No-op where native on PATH.
use path
var loc = (cs-loc julia)
if (not-eq $loc '') {
  for d [$loc/julia-*[nomatch-ok]/bin] { if (and (path:is-dir $d) (not (has-value $paths $d))) { set paths = [$d $@paths]; break } }
}
