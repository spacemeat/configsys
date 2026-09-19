# ghostty: alias to the configsys-managed binary. No-op where native on PATH.
$env.__cs_ghostty = (do { let loc = (cs-loc ghostty); if (($loc != "") and ($loc | path exists)) { $loc } else { "" } })
def --wrapped ghostty [...rest] { if ($env.__cs_ghostty? | is-not-empty) { ^$env.__cs_ghostty ...$rest } else { ^ghostty ...$rest } }
