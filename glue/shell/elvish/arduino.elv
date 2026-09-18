# arduino: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc arduino)
if (and (not-eq $loc '') (path:is-regular $loc)) {
  edit:add-var arduino~ {|@a| (external $loc) $@a }
}
