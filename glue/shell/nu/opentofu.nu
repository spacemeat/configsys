# opentofu: alias tofu to the configsys-managed binary. No-op where native on PATH.
$env.__cs_opentofu = (do { let loc = (cs-loc opentofu); if (($loc != "") and ($"($loc)/tofu" | path exists)) { $"($loc)/tofu" } else { "" } })
def --wrapped tofu [...rest] { if ($env.__cs_opentofu? | is-not-empty) { ^$env.__cs_opentofu ...$rest } else { ^tofu ...$rest } }
