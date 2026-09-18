# jetbrains-toolbox: alias `jetbrains-toolbox` to the tarball binary (versioned subdir). No-op where native on PATH.
use path
var loc = (cs-loc jetbrains-toolbox)
if (not-eq $loc '') {
  for c [$loc/jetbrains-toolbox-*[nomatch-ok]/jetbrains-toolbox $loc/jetbrains-toolbox] {
    if (path:is-regular $c) { edit:add-var jetbrains-toolbox~ {|@a| (external $c) $@a }; break }
  }
}
