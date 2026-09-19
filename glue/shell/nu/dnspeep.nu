# dnspeep: alias to the configsys-managed binary. No-op where native on PATH.
$env.__cs_dnspeep = (do { let loc = (cs-loc dnspeep); if (($loc != "") and ($"($loc)/dnspeep" | path exists)) { $"($loc)/dnspeep" } else { "" } })
def --wrapped dnspeep [...rest] { if ($env.__cs_dnspeep? | is-not-empty) { ^$env.__cs_dnspeep ...$rest } else { ^dnspeep ...$rest } }
