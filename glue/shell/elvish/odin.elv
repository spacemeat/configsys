# Odin: tarball dir (root or versioned subdir; no-op when native).
use path
var loc = (cs-loc odin)
if (not-eq $loc '') {
  var added = $false
  for d [$loc/odin-linux-*[nomatch-ok]] { if (and (path:is-dir $d) (not (has-value $paths $d))) { set paths = [$d $@paths]; set added = $true; break } }
  if (and (not $added) (path:is-regular $loc/odin) (not (has-value $paths $loc))) { set paths = [$loc $@paths] }
}
