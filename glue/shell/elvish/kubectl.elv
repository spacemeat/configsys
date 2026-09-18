# kubectl: put the configsys-managed dir on PATH. No-op where native on PATH.
use path
var loc = (cs-loc kubectl)
if (and (not-eq $loc '') (path:is-regular $loc/kubectl) (not (has-value $paths $loc/.))) {
  set paths = [$@paths $loc/.]
}
