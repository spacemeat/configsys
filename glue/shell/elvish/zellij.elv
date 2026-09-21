# zellij: alias to the tarball binary (flat at the install root). No-op where native on PATH.
use path
var loc = (cs-loc zellij)
if (and (not-eq $loc '') (path:is-regular $loc/zellij)) {
  edit:add-var zellij~ {|@a| (external $loc/zellij) $@a }
}
