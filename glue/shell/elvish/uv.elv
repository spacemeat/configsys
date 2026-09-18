# uv: tarball dir (never-auto binding) + `uv tool` bin (~/.local/bin).
use path
var loc = (cs-loc uv)
if (not-eq $loc '') {
  var added = $false
  for d [$loc/uv-*[nomatch-ok]] { if (and (path:is-dir $d) (not (has-value $paths $d))) { set paths = [$d $@paths]; set added = $true; break } }
  if (and (not $added) (path:is-regular $loc/uv) (not (has-value $paths $loc))) { set paths = [$loc $@paths] }
}
if (and (path:is-dir $E:HOME/.local/bin) (not (has-value $paths $E:HOME/.local/bin))) { set paths = [$E:HOME/.local/bin $@paths] }
