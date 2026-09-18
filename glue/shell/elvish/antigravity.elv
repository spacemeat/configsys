# antigravity: alias `antigravity` to the tarball binary (versioned subdir). No-op where native on PATH.
use path
var loc = (cs-loc antigravity)
if (not-eq $loc '') {
  for c [$loc/antigravity $loc/*[nomatch-ok]/antigravity $loc/*[nomatch-ok]/bin/antigravity] {
    if (path:is-regular $c) { edit:add-var antigravity~ {|@a| (external $c) $@a }; break }
  }
}
