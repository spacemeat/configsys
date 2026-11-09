# nim: put the tarball compiler's bin (no-op where native) and its user-install bin dir on PATH.
use path
var loc = (cs-loc nim)
if (and (not-eq $loc '') (path:is-regular $loc/bin/nim) (not (has-value $paths $loc/bin))) {
  set paths = [$loc/bin $@paths]
}
if (and (path:is-dir $E:HOME/.nimble/bin) (not (has-value $paths $E:HOME/.nimble/bin))) {
  set paths = [$@paths $E:HOME/.nimble/bin]
}
