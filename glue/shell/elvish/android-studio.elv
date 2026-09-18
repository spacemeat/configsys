# android-studio: alias `studio`/`android-studio` to the tarball launcher (bin/studio or bin/studio.sh).
use path
var loc = (cs-loc android-studio)
if (not-eq $loc '') {
  for c [$loc/bin/studio $loc/bin/studio.sh] {
    if (path:is-regular $c) {
      edit:add-var studio~ {|@a| (external $c) $@a }
      edit:add-var android-studio~ {|@a| (external $c) $@a }
      break
    }
  }
}
