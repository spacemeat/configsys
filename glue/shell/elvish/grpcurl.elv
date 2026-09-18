# grpcurl: put the configsys-managed dir on PATH. No-op where native on PATH.
use path
var loc = (cs-loc grpcurl)
if (and (not-eq $loc '') (path:is-regular $loc/grpcurl) (not (has-value $paths $loc/.))) {
  set paths = [$loc/. $@paths]
}
