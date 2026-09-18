# rar: put the configsys-managed dir on PATH. No-op where native on PATH.
use path
var loc = (cs-loc rar)
if (and (not-eq $loc '') (path:is-regular $loc/rar/rar) (not (has-value $paths $loc/rar))) {
  set paths = [$loc/rar $@paths]
}
