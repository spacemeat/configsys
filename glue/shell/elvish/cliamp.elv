# cliamp: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc cliamp)
if (and (not-eq $loc '') (path:is-regular $loc/cliamp)) {
  edit:add-var cliamp~ {|@a| (external $loc/cliamp) $@a }
}
