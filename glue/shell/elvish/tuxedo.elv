# tuxedo: alias to the tarball binary (versioned subdir). No-op where native on PATH.
use path
var loc = (cs-loc tuxedo)
if (not-eq $loc '') {
  for c [$loc/tuxedo-*[nomatch-ok]/tuxedo] {
    if (path:is-regular $c) { edit:add-var tuxedo~ {|@a| (external $c) $@a }; break }
  }
}
