# k9s: alias to the configsys-managed binary. No-op where native on PATH.
$env.__cs_k9s = (do { let loc = (cs-loc k9s); if (($loc != "") and ($"($loc)/k9s" | path exists)) { $"($loc)/k9s" } else { "" } })
def --wrapped k9s [...rest] { if ($env.__cs_k9s? | is-not-empty) { ^$env.__cs_k9s ...$rest } else { ^k9s ...$rest } }
