# lazygit: alias to the configsys-managed binary. No-op where native on PATH.
$env.__cs_lazygit = (do { let loc = (cs-loc lazygit); if (($loc != "") and ($"($loc)/lazygit" | path exists)) { $"($loc)/lazygit" } else { "" } })
def --wrapped lazygit [...rest] { if ($env.__cs_lazygit? | is-not-empty) { ^$env.__cs_lazygit ...$rest } else { ^lazygit ...$rest } }
