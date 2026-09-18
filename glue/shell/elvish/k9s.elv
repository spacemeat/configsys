# k9s: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc k9s)
if (and (not-eq $loc '') (path:is-regular $loc/k9s)) {
  edit:add-var k9s~ {|@a| (external $loc/k9s) $@a }
}
