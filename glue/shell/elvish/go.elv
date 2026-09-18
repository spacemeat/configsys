# Go: tarball toolchain (SDK dir; no-op when native) + `go install` binaries (GOBIN) on PATH.
use path
var loc = (cs-loc go)
if (and (not-eq $loc '') (path:is-regular $loc/bin/go) (not (has-value $paths $loc/bin))) {
  set paths = [$loc/bin $@paths]
}
var gobin = $E:HOME/go/bin
if (has-env GOBIN) { set gobin = $E:GOBIN }
if (not (has-value $paths $gobin)) { set paths = [$@paths $gobin] }
