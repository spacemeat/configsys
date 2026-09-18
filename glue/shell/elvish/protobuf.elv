# protobuf: put the configsys-managed dir on PATH. No-op where native on PATH.
use path
var loc = (cs-loc protobuf)
if (and (not-eq $loc '') (path:is-regular $loc/bin/protoc) (not (has-value $paths $loc/bin))) {
  set paths = [$@paths $loc/bin]
}
