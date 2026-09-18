# jq: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc jq)
if (and (not-eq $loc '') (path:is-regular $loc/jq)) {
  edit:add-var jq~ {|@a| (external $loc/jq) $@a }
}
