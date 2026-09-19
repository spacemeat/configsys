# micro: alias to the tarball binary (versioned subdir). No-op where native.
$env.__cs_micro = (do { let loc = (cs-loc micro); if ($loc == "") { "" } else { ((glob $"($loc)/micro-*/micro") | where {|p| ($p | path exists)} | get 0? | default "") } })
def --wrapped micro [...rest] { if ($env.__cs_micro? | is-not-empty) { ^$env.__cs_micro ...$rest } else { ^micro ...$rest } }
