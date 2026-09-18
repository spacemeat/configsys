# fossil: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc fossil)
if (and (not-eq $loc '') (path:is-regular $loc/fossil)) {
  edit:add-var fossil~ {|@a| (external $loc/fossil) $@a }
}
