# bazelisk: alias to the tarball launcher, also as `bazel` (drop-in). No-op where native.
use path
var loc = (cs-loc bazelisk)
if (and (not-eq $loc '') (path:is-regular $loc/bazelisk)) {
  edit:add-var bazelisk~ {|@a| (external $loc/bazelisk) $@a }
  edit:add-var bazel~ {|@a| (external $loc/bazelisk) $@a }
}
