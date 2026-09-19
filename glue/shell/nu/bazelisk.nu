# bazelisk: alias to the tarball launcher, also as bazel (drop-in). No-op where native.
$env.__cs_bazelisk = (do { let loc = (cs-loc bazelisk); if (($loc != "") and ($"($loc)/bazelisk" | path exists)) { $"($loc)/bazelisk" } else { "" } })
def --wrapped bazelisk [...rest] { if ($env.__cs_bazelisk? | is-not-empty) { ^$env.__cs_bazelisk ...$rest } else { ^bazelisk ...$rest } }
def --wrapped bazel [...rest] { if ($env.__cs_bazelisk? | is-not-empty) { ^$env.__cs_bazelisk ...$rest } else { ^bazel ...$rest } }
