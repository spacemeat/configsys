# cliamp: alias to the configsys-managed binary. No-op where native on PATH.
$env.__cs_cliamp = (do { let loc = (cs-loc cliamp); if (($loc != "") and ($"($loc)/cliamp" | path exists)) { $"($loc)/cliamp" } else { "" } })
def --wrapped cliamp [...rest] { if ($env.__cs_cliamp? | is-not-empty) { ^$env.__cs_cliamp ...$rest } else { ^cliamp ...$rest } }
