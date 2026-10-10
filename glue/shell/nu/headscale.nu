# headscale: alias to the configsys-managed binary. No-op where native on PATH.
$env.__cs_headscale = (do { let loc = (cs-loc headscale); if (($loc != "") and ($"($loc)/headscale" | path exists)) { $"($loc)/headscale" } else { "" } })
def --wrapped headscale [...rest] { if ($env.__cs_headscale? | is-not-empty) { ^$env.__cs_headscale ...$rest } else { ^headscale ...$rest } }
