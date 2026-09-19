# arduino: alias to the configsys-managed binary. No-op where native on PATH.
$env.__cs_arduino = (do { let loc = (cs-loc arduino); if (($loc != "") and ($loc | path exists)) { $loc } else { "" } })
def --wrapped arduino [...rest] { if ($env.__cs_arduino? | is-not-empty) { ^$env.__cs_arduino ...$rest } else { ^arduino ...$rest } }
