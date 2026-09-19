# fossil: alias to the configsys-managed binary. No-op where native on PATH.
$env.__cs_fossil = (do { let loc = (cs-loc fossil); if (($loc != "") and ($"($loc)/fossil" | path exists)) { $"($loc)/fossil" } else { "" } })
def --wrapped fossil [...rest] { if ($env.__cs_fossil? | is-not-empty) { ^$env.__cs_fossil ...$rest } else { ^fossil ...$rest } }
