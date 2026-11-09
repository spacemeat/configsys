# neovim: alias v/vi to the configsys-managed binary. No-op where native on PATH: nu can't define a
# command conditionally, so without a managed binary each one runs the EXTERNAL of its own name — as if
# undefined, like the other shells (your system vi stays vi).
$env.__cs_neovim = (do { let loc = (cs-loc neovim); if (($loc != "") and ($loc | path exists)) { $loc } else { "" } })
def --wrapped v [...rest] { if ($env.__cs_neovim? | is-not-empty) { ^$env.__cs_neovim ...$rest } else { ^v ...$rest } }
def --wrapped vi [...rest] { if ($env.__cs_neovim? | is-not-empty) { ^$env.__cs_neovim ...$rest } else { ^vi ...$rest } }
