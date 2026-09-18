# lazysql: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc lazysql)
if (and (not-eq $loc '') (path:is-regular $loc/lazysql)) {
  edit:add-var lazysql~ {|@a| (external $loc/lazysql) $@a }
}
