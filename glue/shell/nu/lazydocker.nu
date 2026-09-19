# lazydocker: alias to the configsys-managed binary. No-op where native on PATH.
$env.__cs_lazydocker = (do { let loc = (cs-loc lazydocker); if (($loc != "") and ($"($loc)/lazydocker" | path exists)) { $"($loc)/lazydocker" } else { "" } })
def --wrapped lazydocker [...rest] { if ($env.__cs_lazydocker? | is-not-empty) { ^$env.__cs_lazydocker ...$rest } else { ^lazydocker ...$rest } }
