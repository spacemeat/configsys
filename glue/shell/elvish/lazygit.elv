# lazygit: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc lazygit)
if (and (not-eq $loc '') (path:is-regular $loc/lazygit)) {
  edit:add-var lazygit~ {|@a| (external $loc/lazygit) $@a }
}
