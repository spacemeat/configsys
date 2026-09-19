# helix: alias hx to the tarball binary (versioned subdir). No-op where native.
$env.__cs_helix = (do { let loc = (cs-loc helix); if ($loc == "") { "" } else { ((glob $"($loc)/helix-*-x86_64-linux/hx") | where {|p| ($p | path exists)} | get 0? | default "") } })
def --wrapped hx [...rest] { if ($env.__cs_helix? | is-not-empty) { ^$env.__cs_helix ...$rest } else { ^hx ...$rest } }
