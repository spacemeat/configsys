# tuxedo: alias to the tarball binary (versioned subdir). No-op where native.
$env.__cs_tuxedo = (do { let loc = (cs-loc tuxedo); if ($loc == "") { "" } else { ((glob $"($loc)/tuxedo-*/tuxedo") | where {|p| ($p | path exists)} | get 0? | default "") } })
def --wrapped tuxedo [...rest] { if ($env.__cs_tuxedo? | is-not-empty) { ^$env.__cs_tuxedo ...$rest } else { ^tuxedo ...$rest } }
