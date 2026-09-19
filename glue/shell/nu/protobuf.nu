# protobuf: put the configsys-managed dir on PATH. No-op where native on PATH.
let protobuf_loc = (cs-loc protobuf)
if (($protobuf_loc != "") and ($"($protobuf_loc)/bin/protoc" | path exists)) { cs-append $"($protobuf_loc)/bin" }
