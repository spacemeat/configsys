# tuios: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc tuios)
if (and (not-eq $loc '') (path:is-regular $loc/tuios)) {
  edit:add-var tuios~ {|@a| (external $loc/tuios) $@a }
}
