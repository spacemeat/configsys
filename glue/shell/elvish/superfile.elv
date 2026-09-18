# superfile: alias `spf` to the tarball binary (versioned subdir). No-op where native on PATH.
use path
var loc = (cs-loc superfile)
if (not-eq $loc '') {
  for c [$loc/dist/superfile-linux-*[nomatch-ok]/spf] {
    if (path:is-regular $c) { edit:add-var spf~ {|@a| (external $c) $@a }; break }
  }
}
