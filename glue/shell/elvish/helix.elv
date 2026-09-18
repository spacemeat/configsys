# helix: alias `hx` to the tarball binary (versioned subdir). No-op where native on PATH.
use path
var loc = (cs-loc helix)
if (not-eq $loc '') {
  for c [$loc/helix-*[nomatch-ok]-x86_64-linux/hx] {
    if (path:is-regular $c) { edit:add-var hx~ {|@a| (external $c) $@a }; break }
  }
}
