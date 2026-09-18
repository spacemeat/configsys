# xh: alias `xh` to the tarball binary (versioned subdir). No-op where native on PATH.
use path
var loc = (cs-loc xh)
if (not-eq $loc '') {
  for c [$loc/xh-*[nomatch-ok]/xh $loc/xh] {
    if (path:is-regular $c) { edit:add-var xh~ {|@a| (external $c) $@a }; break }
  }
}
