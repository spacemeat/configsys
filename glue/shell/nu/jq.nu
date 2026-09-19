# jq: alias to the configsys-managed binary. No-op where native on PATH.
$env.__cs_jq = (do { let loc = (cs-loc jq); if (($loc != "") and ($"($loc)/jq" | path exists)) { $"($loc)/jq" } else { "" } })
def --wrapped jq [...rest] { if ($env.__cs_jq? | is-not-empty) { ^$env.__cs_jq ...$rest } else { ^jq ...$rest } }
