# yazi: alias `yazi` to the tarball binary (versioned subdir). No-op where native on PATH.
use path
var loc = (cs-loc yazi)
if (not-eq $loc '') {
  for c [$loc/yazi-*[nomatch-ok]-unknown-linux-*[nomatch-ok]/yazi] {
    if (path:is-regular $c) { edit:add-var yazi~ {|@a| (external $c) $@a }; break }
  }
}
