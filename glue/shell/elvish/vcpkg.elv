# vcpkg: export VCPKG_ROOT + put the `vcpkg` tool on PATH (CMake reads VCPKG_ROOT). No-op if absent.
use path
var loc = (cs-loc vcpkg)
if (and (not-eq $loc '') (path:is-regular $loc/vcpkg)) {
  set-env VCPKG_ROOT $loc
  if (not (has-value $paths $loc)) { set paths = [$loc $@paths] }
}
