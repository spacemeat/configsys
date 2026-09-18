# ripgrep: expose the tarball `rg` (a versioned subdir) as `rg`. No-op where ripgrep is native on PATH.
# Resolve the binary ONCE at load into an env cache (a top-level `let` wouldn't persist to the REPL,
# but $env does), so the `rg` command reads a cached path instead of shelling out to configsys on every
# call. `do { … }` gives the multi-statement value its own scope (a bare `( let … )` doesn't scope the
# binding to the next line). As with fd, the def is defined unconditionally (parse-time scoping) and
# self-guards.
$env.__cs_rg = (do {
  let loc = (cs-loc ripgrep)
  if ($loc != "") { glob $"($loc)/ripgrep-*/rg" | get 0? | default "" } else { "" }
})
def --wrapped rg [...rest] {
  if ($env.__cs_rg? | is-not-empty) { ^$env.__cs_rg ...$rest } else { ^rg ...$rest }
}
