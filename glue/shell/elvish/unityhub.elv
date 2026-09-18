# unityhub: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc unityhub)
if (and (not-eq $loc '') (path:is-regular $loc)) {
  edit:add-var unityhub~ {|@a| (external $loc) $@a }
}
