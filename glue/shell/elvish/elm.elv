# elm: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc elm)
if (and (not-eq $loc '') (path:is-regular $loc/elm)) {
  edit:add-var elm~ {|@a| (external $loc/elm) $@a }
}
