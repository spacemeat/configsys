# elm: alias to the configsys-managed binary. No-op where native on PATH.
$env.__cs_elm = (do { let loc = (cs-loc elm); if (($loc != "") and ($"($loc)/elm" | path exists)) { $"($loc)/elm" } else { "" } })
def --wrapped elm [...rest] { if ($env.__cs_elm? | is-not-empty) { ^$env.__cs_elm ...$rest } else { ^elm ...$rest } }
