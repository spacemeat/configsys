# neovim: alias v/vi to the configsys-managed binary. No-op where native on PATH.
$env.__cs_neovim = (do { let loc = (cs-loc neovim); if (($loc != "") and ($loc | path exists)) { $loc } else { "" } })
def --wrapped v [...rest] { if ($env.__cs_neovim? | is-not-empty) { ^$env.__cs_neovim ...$rest } else { ^nvim ...$rest } }
def --wrapped vi [...rest] { if ($env.__cs_neovim? | is-not-empty) { ^$env.__cs_neovim ...$rest } else { ^nvim ...$rest } }
