# zellij: alias to the tarball binary (flat at the install root). No-op where native.
$env.__cs_zellij = (do { let loc = (cs-loc zellij); if ($loc == "") { "" } else { ((glob $"($loc)/zellij") | where {|p| ($p | path exists)} | get 0? | default "") } })
def --wrapped zellij [...rest] { if ($env.__cs_zellij? | is-not-empty) { ^$env.__cs_zellij ...$rest } else { ^zellij ...$rest } }
