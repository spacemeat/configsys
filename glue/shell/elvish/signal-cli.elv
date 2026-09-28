# signal-cli: prepend the tarball install dir to PATH. No-op where native on PATH.
use path
var loc = (cs-loc signal-cli)
if (and (not-eq $loc '') (path:is-regular $loc/signal-cli) (not (has-value $paths $loc))) {
  set paths = [$loc $@paths]
}
