# v: put the configsys-managed dir on PATH. No-op where native on PATH.
use path
var loc = (cs-loc v)
if (and (not-eq $loc '') (path:is-regular $loc/v/v) (not (has-value $paths $loc/v))) {
  set paths = [$loc/v $@paths]
}
