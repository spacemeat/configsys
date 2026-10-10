# herdr: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc herdr)
if (and (not-eq $loc '') (path:is-regular $loc/herdr)) {
  edit:add-var herdr~ {|@a| (external $loc/herdr) $@a }
}
