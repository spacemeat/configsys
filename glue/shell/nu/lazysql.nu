# lazysql: alias to the configsys-managed binary. No-op where native on PATH.
$env.__cs_lazysql = (do { let loc = (cs-loc lazysql); if (($loc != "") and ($"($loc)/lazysql" | path exists)) { $"($loc)/lazysql" } else { "" } })
def --wrapped lazysql [...rest] { if ($env.__cs_lazysql? | is-not-empty) { ^$env.__cs_lazysql ...$rest } else { ^lazysql ...$rest } }
