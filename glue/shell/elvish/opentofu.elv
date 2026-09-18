# opentofu: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc opentofu)
if (and (not-eq $loc '') (path:is-regular $loc/tofu)) {
  edit:add-var tofu~ {|@a| (external $loc/tofu) $@a }
}
