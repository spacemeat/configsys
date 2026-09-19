# tree-sitter-cli: alias to the configsys-managed binary. No-op where native on PATH.
$env.__cs_tree_sitter_cli = (do { let loc = (cs-loc tree-sitter-cli); if (($loc != "") and ($"($loc)/tree-sitter" | path exists)) { $"($loc)/tree-sitter" } else { "" } })
def --wrapped tree-sitter [...rest] { if ($env.__cs_tree_sitter_cli? | is-not-empty) { ^$env.__cs_tree_sitter_cli ...$rest } else { ^tree-sitter ...$rest } }
