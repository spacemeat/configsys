# websocat: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc websocat)
if (and (not-eq $loc '') (path:is-regular $loc/websocat)) {
  edit:add-var websocat~ {|@a| (external $loc/websocat) $@a }
}
