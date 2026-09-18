# micro: alias `micro` to the tarball binary (versioned subdir). No-op where native on PATH.
use path
var loc = (cs-loc micro)
if (not-eq $loc '') {
  for c [$loc/micro-*[nomatch-ok]/micro] {
    if (path:is-regular $c) { edit:add-var micro~ {|@a| (external $c) $@a }; break }
  }
}
