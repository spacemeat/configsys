# just: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc just)
if (and (not-eq $loc '') (path:is-regular $loc/just)) {
  edit:add-var just~ {|@a| (external $loc/just) $@a }
}
