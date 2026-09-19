# superfile: alias spf to the tarball binary (versioned subdir). No-op where native.
$env.__cs_superfile = (do { let loc = (cs-loc superfile); if ($loc == "") { "" } else { ((glob $"($loc)/dist/superfile-linux-*/spf") | where {|p| ($p | path exists)} | get 0? | default "") } })
def --wrapped spf [...rest] { if ($env.__cs_superfile? | is-not-empty) { ^$env.__cs_superfile ...$rest } else { ^spf ...$rest } }
