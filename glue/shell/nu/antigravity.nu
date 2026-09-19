# antigravity: alias to the tarball binary (versioned subdir). No-op where native.
$env.__cs_antigravity = (do { let loc = (cs-loc antigravity); if ($loc == "") { "" } else { ([$"($loc)/antigravity"] ++ (glob $"($loc)/*/antigravity") ++ (glob $"($loc)/*/bin/antigravity") | where {|p| ($p | path exists)} | get 0? | default "") } })
def --wrapped antigravity [...rest] { if ($env.__cs_antigravity? | is-not-empty) { ^$env.__cs_antigravity ...$rest } else { ^antigravity ...$rest } }
