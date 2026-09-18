# lazydocker: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc lazydocker)
if (and (not-eq $loc '') (path:is-regular $loc/lazydocker)) {
  edit:add-var lazydocker~ {|@a| (external $loc/lazydocker) $@a }
}
