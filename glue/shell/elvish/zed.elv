# zed: alias to the tarball binary (release unpacks a zed.app bundle). No-op where native/script-installed.
use path
var loc = (cs-loc zed)
if (and (not-eq $loc '') (path:is-regular $loc/zed.app/bin/zed)) {
  edit:add-var zed~ {|@a| (external $loc/zed.app/bin/zed) $@a }
}
