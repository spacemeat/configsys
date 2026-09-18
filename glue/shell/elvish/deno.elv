# Deno: tarball dir (no-op when native) + `deno install` global scripts.
use path
var loc = (cs-loc deno)
if (and (not-eq $loc '') (path:is-regular $loc/deno) (not (has-value $paths $loc))) { set paths = [$loc $@paths] }
if (and (path:is-dir $E:HOME/.deno/bin) (not (has-value $paths $E:HOME/.deno/bin))) { set paths = [$@paths $E:HOME/.deno/bin] }
