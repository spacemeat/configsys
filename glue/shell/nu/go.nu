# Go: tarball toolchain (SDK dir; no-op when native) + `go install` binaries (GOBIN) on PATH.
# $env.PATH is a list in nushell; set it at TOP LEVEL (persists to the REPL). `let` here is fine — it
# is used within this same file's evaluation, not read back later. `uniq` keeps the entry from piling
# up on re-source.
let go_loc = (cs-loc go)
if ($go_loc != "" and ($"($go_loc)/bin/go" | path exists)) {
  $env.PATH = ($env.PATH | prepend $"($go_loc)/bin" | uniq)
}
let gobin = ($env.GOBIN? | default $"($env.HOME)/go/bin")
$env.PATH = ($env.PATH | append $gobin | uniq)
