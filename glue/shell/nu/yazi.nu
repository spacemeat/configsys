# yazi: alias to the tarball binary (versioned subdir). No-op where native.
$env.__cs_yazi = (do { let loc = (cs-loc yazi); if ($loc == "") { "" } else { ((glob $"($loc)/yazi-*-unknown-linux-*/yazi") | where {|p| ($p | path exists)} | get 0? | default "") } })
def --wrapped yazi [...rest] { if ($env.__cs_yazi? | is-not-empty) { ^$env.__cs_yazi ...$rest } else { ^yazi ...$rest } }
