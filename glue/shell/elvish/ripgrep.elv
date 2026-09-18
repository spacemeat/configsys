# ripgrep: alias `rg` to the tarball binary (versioned subdir). No-op where native on PATH.
use path
var loc = (cs-loc ripgrep)
if (not-eq $loc '') {
  for c [$loc/ripgrep-*[nomatch-ok]/rg] {
    if (path:is-regular $c) { edit:add-var rg~ {|@a| (external $c) $@a }; break }
  }
}
