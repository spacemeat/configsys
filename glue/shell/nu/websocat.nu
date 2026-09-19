# websocat: alias to the configsys-managed binary. No-op where native on PATH.
$env.__cs_websocat = (do { let loc = (cs-loc websocat); if (($loc != "") and ($"($loc)/websocat" | path exists)) { $"($loc)/websocat" } else { "" } })
def --wrapped websocat [...rest] { if ($env.__cs_websocat? | is-not-empty) { ^$env.__cs_websocat ...$rest } else { ^websocat ...$rest } }
