# just: alias to the configsys-managed binary. No-op where native on PATH.
$env.__cs_just = (do { let loc = (cs-loc just); if (($loc != "") and ($"($loc)/just" | path exists)) { $"($loc)/just" } else { "" } })
def --wrapped just [...rest] { if ($env.__cs_just? | is-not-empty) { ^$env.__cs_just ...$rest } else { ^just ...$rest } }
