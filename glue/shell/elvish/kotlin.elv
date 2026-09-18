# kotlin: put the tarball compiler's bin (kotlinc/bin) on PATH. No-op where native on PATH.
use path
var loc = (cs-loc kotlin)
if (and (not-eq $loc '') (path:is-dir $loc/kotlinc/bin) (not (has-value $paths $loc/kotlinc/bin))) {
  set paths = [$@paths $loc/kotlinc/bin]
}
