# tuios: alias to the configsys-managed binary. No-op where native on PATH.
$env.__cs_tuios = (do { let loc = (cs-loc tuios); if (($loc != "") and ($"($loc)/tuios" | path exists)) { $"($loc)/tuios" } else { "" } })
def --wrapped tuios [...rest] { if ($env.__cs_tuios? | is-not-empty) { ^$env.__cs_tuios ...$rest } else { ^tuios ...$rest } }
