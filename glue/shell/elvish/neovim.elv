# neovim: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc neovim)
if (and (not-eq $loc '') (path:is-regular $loc)) {
  edit:add-var v~ {|@a| (external $loc) $@a }
  edit:add-var vi~ {|@a| (external $loc) $@a }
}
