# btop: alias to the tarball-installed binary (versioned subdir / candidate paths). No-op where native.
use path
var loc = (cs-loc btop)
if (not-eq $loc '') {
  for c [$loc/btop/bin/btop $loc/bin/btop] {
    if (path:is-regular $c) { edit:add-var btop~ {|@a| (external $c) $@a }; break }
  }
}
