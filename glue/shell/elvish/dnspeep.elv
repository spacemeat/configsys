# dnspeep: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc dnspeep)
if (and (not-eq $loc '') (path:is-regular $loc/dnspeep)) {
  edit:add-var dnspeep~ {|@a| (external $loc/dnspeep) $@a }
}
