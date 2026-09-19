# gleam: put the configsys-managed dir on PATH. No-op where native on PATH.
let gleam_loc = (cs-loc gleam)
if (($gleam_loc != "") and ($"($gleam_loc)/gleam" | path exists)) { cs-prepend $gleam_loc }
