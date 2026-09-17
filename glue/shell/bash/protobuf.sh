# protobuf: add the tarball-installed protoc's bin to PATH (zip unpacks into bin/ + include/).
# No-op where protobuf is native (the default everywhere it's packaged) and protoc is on PATH.
_pb=$(configsys location protobuf 2>/dev/null)
[ -n "$_pb" ] && [ -x "$_pb/bin/protoc" ] && case ":$PATH:" in *":$_pb/bin:"*) ;; *) PATH="$PATH:$_pb/bin"; export PATH ;; esac
unset _pb
