# herdr: alias to the configsys-managed binary. No-op where native on PATH.
$env.__cs_herdr = (do { let loc = (cs-loc herdr); if (($loc != "") and ($"($loc)/herdr" | path exists)) { $"($loc)/herdr" } else { "" } })
def --wrapped herdr [...rest] { if ($env.__cs_herdr? | is-not-empty) { ^$env.__cs_herdr ...$rest } else { ^herdr ...$rest } }
