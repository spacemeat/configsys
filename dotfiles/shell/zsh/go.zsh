# Go: tarball toolchain (SDK dir; no-op when native) + `go install` binaries (GOBIN) on PATH.
_go=$(configsys location go 2>/dev/null)
[ -n "$_go" ] && [ -x "$_go/bin/go" ] && export PATH="$_go/bin:$PATH"
unset _go
export PATH="$PATH:${GOBIN:-$HOME/go/bin}"
