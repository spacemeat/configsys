# zed: alias to the tarball binary (zed.app bundle). No-op where native/script-installed.
$env.__cs_zed = (do { let loc = (cs-loc zed); if (($loc != "") and ($"($loc)/zed.app/bin/zed" | path exists)) { $"($loc)/zed.app/bin/zed" } else { "" } })
def --wrapped zed [...rest] { if ($env.__cs_zed? | is-not-empty) { ^$env.__cs_zed ...$rest } else { ^zed ...$rest } }
