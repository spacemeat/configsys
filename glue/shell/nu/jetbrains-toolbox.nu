# jetbrains-toolbox: alias to the tarball binary (versioned subdir). No-op where native.
$env.__cs_jetbrains_toolbox = (do { let loc = (cs-loc jetbrains-toolbox); if ($loc == "") { "" } else { ((glob $"($loc)/jetbrains-toolbox-*/jetbrains-toolbox") ++ [$"($loc)/jetbrains-toolbox"] | where {|p| ($p | path exists)} | get 0? | default "") } })
def --wrapped jetbrains-toolbox [...rest] { if ($env.__cs_jetbrains_toolbox? | is-not-empty) { ^$env.__cs_jetbrains_toolbox ...$rest } else { ^jetbrains-toolbox ...$rest } }
