# headscale: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc headscale)
if (and (not-eq $loc '') (path:is-regular $loc/headscale)) {
  edit:add-var headscale~ {|@a| (external $loc/headscale) $@a }
}
