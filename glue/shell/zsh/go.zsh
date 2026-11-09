# Go: tarball toolchain (SDK dir; no-op when native) + `go install` binaries (GOBIN) on PATH.
_go=$(cs_loc go)
[ -n "$_go" ] && [ -x "$_go/bin/go" ] && export PATH="$_go/bin:$PATH"
unset _go
_gobin="${GOBIN:-$HOME/go/bin}"
case ":$PATH:" in *":$_gobin:"*) ;; *) export PATH="$PATH:$_gobin" ;; esac   # once, however often sourced
unset _gobin
