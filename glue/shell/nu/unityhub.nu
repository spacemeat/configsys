# unityhub: alias to the configsys-managed binary. No-op where native on PATH.
$env.__cs_unityhub = (do { let loc = (cs-loc unityhub); if (($loc != "") and ($loc | path exists)) { $loc } else { "" } })
def --wrapped unityhub [...rest] { if ($env.__cs_unityhub? | is-not-empty) { ^$env.__cs_unityhub ...$rest } else { ^unityhub ...$rest } }
