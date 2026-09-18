# ghostty: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc ghostty)
if (and (not-eq $loc '') (path:is-regular $loc)) {
  edit:add-var ghostty~ {|@a| (external $loc) $@a }
}
