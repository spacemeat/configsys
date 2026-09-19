# xh: alias to the tarball binary (versioned subdir). No-op where native.
$env.__cs_xh = (do { let loc = (cs-loc xh); if ($loc == "") { "" } else { ((glob $"($loc)/xh-*/xh") ++ [$"($loc)/xh"] | where {|p| ($p | path exists)} | get 0? | default "") } })
def --wrapped xh [...rest] { if ($env.__cs_xh? | is-not-empty) { ^$env.__cs_xh ...$rest } else { ^xh ...$rest } }
