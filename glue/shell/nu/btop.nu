# btop: alias to the tarball-installed binary (candidate paths). No-op where native.
$env.__cs_btop = (do { let loc = (cs-loc btop); if ($loc == "") { "" } else { ([$"($loc)/btop/bin/btop"] ++ [$"($loc)/bin/btop"] | where {|p| ($p | path exists)} | get 0? | default "") } })
def --wrapped btop [...rest] { if ($env.__cs_btop? | is-not-empty) { ^$env.__cs_btop ...$rest } else { ^btop ...$rest } }
